import os
import numpy as np
import torch
import torch.nn as nn
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


_MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.getenv("HYPOXIA_MODEL_PATH", os.path.join(_MODEL_DIR, "best_fold0.pt"))
MODEL_BASE = 64

# Константы для обработки данных
TARGET_HZ = 1.0  # Частота дискретизации 1 Гц
WINDOW_SIZE_SEC = 20 * 60  # 20 минут
WINDOW_SIZE_POINTS = int(WINDOW_SIZE_SEC * TARGET_HZ)  # 1200 точек


RISK_THRESHOLD_LOW = 0.3
RISK_THRESHOLD_MEDIUM = 0.5
RISK_THRESHOLD_HIGH = 0.7


class ResidualBlock(nn.Module):
    def __init__(self, c_in, c_out, k=7, d=1, p_drop=0.1):
        super().__init__()
        pad = (k - 1) // 2 * d
        self.conv1 = nn.Conv1d(c_in, c_out, kernel_size=k, padding=pad, dilation=d)
        self.bn1 = nn.BatchNorm1d(c_out)
        self.conv2 = nn.Conv1d(c_out, c_out, kernel_size=k, padding=pad, dilation=d)
        self.bn2 = nn.BatchNorm1d(c_out)
        self.act = nn.SiLU()
        self.dropout = nn.Dropout(p_drop)
        self.skip = nn.Conv1d(c_in, c_out, 1) if c_in != c_out else nn.Identity()

    def forward(self, x):
        h = self.act(self.bn1(self.conv1(x)))
        h = self.dropout(h)
        h = self.bn2(self.conv2(h))
        x = self.skip(x)
        return self.act(h + x)


class TinyTCN(nn.Module):
    def __init__(self, in_ch=2, base=48, num_classes=1, p_drop=0.1):
        super().__init__()
        self.stem = nn.Conv1d(in_ch, base, kernel_size=7, padding=3)
        self.block1 = ResidualBlock(base, base, k=7, d=1, p_drop=p_drop)
        self.block2 = ResidualBlock(base, base*2, k=7, d=2, p_drop=p_drop)
        self.pool2 = nn.AvgPool1d(2)
        self.block3 = ResidualBlock(base*2, base*2, k=7, d=4, p_drop=p_drop)
        self.block4 = ResidualBlock(base*2, base*4, k=7, d=8, p_drop=p_drop)
        self.pool4 = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(base*4, base*2),
            nn.ReLU(),
            nn.Dropout(p_drop),
            nn.Linear(base*2, num_classes)
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.block1(x)
        x = self.block2(x)
        x = self.pool2(x)
        x = self.block3(x)
        x = self.block4(x)
        x = self.pool4(x)
        x = self.head(x)
        return x.squeeze(-1)


# ============================================================================
# ПРЕДИКТОР ГИПОКСИИ
# ============================================================================
class HypoxiaPredictor:
    """
    Класс для прогнозирования острой гипоксии плода.
    
    Модель работает на окнах данных длиной 20 минут (1200 точек при 1 Гц).
    Первое предсказание делается после накопления 20 минут данных,
    затем каждую минуту на последних 20 минутах.
    """
    
    def __init__(self, model_path: str = MODEL_PATH, device: Optional[str] = None):
        """
        Инициализация предиктора.
        
        Args:
            model_path: Путь к файлу с весами модели
            device: Устройство для вычислений ('cuda', 'cpu' или None для автоопределения)
        """
        self.model_path = model_path
        self.model: Optional[nn.Module] = None
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.is_loaded = False
        
        # Временные метки последнего предсказания
        self.last_prediction_time: float = -1.0
        self.prediction_interval_sec: float = 60.0  # Каждую минуту
        
        # Загрузка модели
        self._load_model()
    
    def _load_model(self) -> bool:
        """
        Загружает предобученную модель.
        
        Returns:
            True если модель загружена успешно, False иначе
        """
        if not os.path.exists(self.model_path):
            logger.warning(f"Модель гипоксии не найдена по пути: {self.model_path}")
            logger.info("Предсказания гипоксии будут отключены")
            return False
        
        try:
            self.model = TinyTCN(in_ch=2, base=MODEL_BASE, num_classes=1, p_drop=0.1)
            
            # Загрузка checkpoint
            checkpoint = torch.load(self.model_path, map_location=self.device)
            
            # Если это полный checkpoint (с ключом 'model'), извлекаем веса
            if isinstance(checkpoint, dict) and 'model' in checkpoint:
                state_dict = checkpoint['model']
            else:
                state_dict = checkpoint
            
            self.model.load_state_dict(state_dict)
            
            self.model.to(self.device)
            self.model.eval()
            
            self.is_loaded = True
            logger.info(f"✓ Модель гипоксии загружена: {self.model_path}")
            logger.info(f"  Устройство: {self.device}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка загрузки модели гипоксии: {e}")
            self.model = None
            self.is_loaded = False
            return False
    
    def _preprocess_data(
        self, 
        time_arr: np.ndarray, 
        fhr_arr: np.ndarray, 
        uterus_arr: np.ndarray
    ) -> Optional[torch.Tensor]:
        """
        Предобработка данных для модели.
        
        Args:
            time_arr: Временные метки
            fhr_arr: ЧСС плода (bpm)
            uterus_arr: Маточные сокращения
            
        Returns:
            Тензор формы (1, 2, 1200) или None при ошибке
        """
        try:
            # Интерполяция на равномерную сетку 1 Гц
            fhr_1hz = self._interp_to_1hz(time_arr, fhr_arr)
            uterus_1hz = self._interp_to_1hz(time_arr, uterus_arr)
            
            # Клиппинг физиологических значений
            fhr_1hz = np.clip(fhr_1hz, 50.0, 210.0)
            uterus_1hz = np.clip(uterus_1hz, -5.0, 100.0)
            
            # Берем последние 1200 точек (20 минут)
            if len(fhr_1hz) < WINDOW_SIZE_POINTS:
                # Недостаточно данных
                return None
            
            fhr_window = fhr_1hz[-WINDOW_SIZE_POINTS:]
            uterus_window = uterus_1hz[-WINDOW_SIZE_POINTS:]
            
            # Z-нормализация
            fhr_z = self._zscore(fhr_window)
            uterus_z = self._zscore(uterus_window)
            
            # Формирование тензора (1, 2, 1200)
            x = np.stack([fhr_z, uterus_z], axis=0)
            x = torch.from_numpy(x).float().unsqueeze(0)
            
            return x
            
        except Exception as e:
            logger.error(f"Ошибка предобработки данных: {e}")
            return None
    
    @staticmethod
    def _interp_to_1hz(times: np.ndarray, arr: np.ndarray) -> np.ndarray:
        """Интерполяция массива по времени на равномерную сетку 1 Гц."""
        t0, t1 = float(times[0]), float(times[-1])
        nsec = int(round((t1 - t0)))
        grid = np.arange(t0, t0 + nsec + 1e-6, 1.0, dtype=np.float64)
        
        # Гарантия возрастания времени
        t = np.asarray(times, dtype=np.float64)
        if np.any(np.diff(t) <= 0):
            idx = np.argsort(t)
            t = t[idx]
            a = arr[idx]
        else:
            a = arr
        
        out = np.interp(grid, t, a)
        return out.astype(np.float32)
    
    @staticmethod
    def _zscore(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
        """Z-нормализация с защитой от деления на 0."""
        m = float(np.nanmean(x))
        s = float(np.nanstd(x))
        if not np.isfinite(s) or s < eps:
            s = 1.0
        return ((x - m) / s).astype(np.float32)
    
    def should_predict(self, current_time_sec: float, data_length_sec: float) -> bool:
        """
        Определяет, нужно ли делать предсказание в данный момент.
        
        Args:
            current_time_sec: Текущее время (секунды от начала)
            data_length_sec: Доступная длительность данных
            
        Returns:
            True если пора делать предсказание
        """
        # Проверка 1: Есть ли достаточно данных (минимум 20 минут)
        if data_length_sec < WINDOW_SIZE_SEC:
            return False
        
        # Проверка 2: Первое предсказание после 20 минут
        if self.last_prediction_time < 0:
            return True
        
        # Проверка 3: Прошла ли минута с последнего предсказания
        time_since_last = current_time_sec - self.last_prediction_time
        return time_since_last >= self.prediction_interval_sec
    
    def predict(
        self, 
        time_arr: np.ndarray, 
        fhr_arr: np.ndarray, 
        uterus_arr: np.ndarray,
        current_time_sec: float
    ) -> Optional[Tuple[float, str]]:
        """
        Делает предсказание вероятности острой гипоксии.
        
        Args:
            time_arr: Временные метки
            fhr_arr: ЧСС плода
            uterus_arr: Маточные сокращения
            current_time_sec: Текущее время мониторинга
            
        Returns:
            Кортеж (вероятность, текст_предупреждения) или None если предсказание невозможно
        """

        if not self.is_loaded or self.model is None:
            return None
        

        data_length_sec = time_arr[-1] - time_arr[0] if len(time_arr) > 0 else 0
        if not self.should_predict(current_time_sec, data_length_sec):
            return None
        

        x = self._preprocess_data(time_arr, fhr_arr, uterus_arr)
        if x is None:
            return None
        

        try:
            with torch.no_grad():
                x = x.to(self.device)
                logits = self.model(x)
                prob = torch.sigmoid(logits).item()

            self.last_prediction_time = current_time_sec
            
            warning = self._format_warning(prob)
            
            logger.info(f"Предсказание гипоксии: {prob:.3f} (время: {current_time_sec:.0f}с)")
            
            return prob, warning
            
        except Exception as e:
            logger.error(f"Ошибка при предсказании: {e}")
            return None
    
    @staticmethod
    def _format_warning(probability: float) -> str:
        """
        Форматирует предупреждение на основе вероятности.
        
        Args:
            probability: Вероятность острой гипоксии (0-1)
            
        Returns:
            Отформатированное текстовое предупреждение
        """
        risk_level = "НИЗКИЙ"
        emoji = ""
        recommendation = "Продолжить плановое наблюдение"
        
        if probability >= RISK_THRESHOLD_HIGH:
            risk_level = "КРИТИЧЕСКИЙ"
            emoji = ""
            recommendation = "ТРЕБУЕТСЯ НЕМЕДЛЕННАЯ КОНСУЛЬТАЦИЯ ВРАЧА"
        elif probability >= RISK_THRESHOLD_MEDIUM:
            risk_level = "ВЫСОКИЙ"
            emoji = ""
            recommendation = "Рекомендуется усиленное наблюдение и готовность к вмешательству"
        elif probability >= RISK_THRESHOLD_LOW:
            risk_level = "УМЕРЕННЫЙ"
            emoji = ""
            recommendation = "Продолжить тщательное наблюдение"
        
        warning = (
            f"{emoji} Вероятность острой гипоксии плода: {probability*100:.1f}"
        )
        
        return warning
    
    def reset(self):
        """Сбрасывает состояние предиктора (для новой сессии мониторинга)."""
        self.last_prediction_time = -1.0
        logger.debug("Предиктор гипоксии сброшен")


_global_predictor: Optional[HypoxiaPredictor] = None


def get_predictor() -> Optional[HypoxiaPredictor]:
    """
    Возвращает глобальный экземпляр предиктора гипоксии.
    Создает его при первом вызове.
    
    Returns:
        HypoxiaPredictor или None если модель не загружена
    """
    global _global_predictor
    
    if _global_predictor is None:
        _global_predictor = HypoxiaPredictor()
        
        if not _global_predictor.is_loaded:
            logger.warning("Предиктор гипоксии недоступен (модель не загружена)")
            return None
    
    return _global_predictor if _global_predictor.is_loaded else None