import os
import math
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Literal
import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import json
from contextlib import asynccontextmanager
from collections import deque

from processing import (
    compute_signals_and_statuses,
    generate_warnings,
)
from hypoxia_predictor import get_predictor

FS_DEFAULT = 7.87


ANNOTATION_FAST_PERIOD_SEC = 30.0
ANNOTATION_FULL_PERIOD_SEC = 60.0
MIN_DATA_FOR_FULL_ANALYTICS_SEC = 90.0
ANNOTATION_POLL_REAL_SEC = 0.3


# Размер буфера для последних сообщений (для новых подключений)
MESSAGE_BUFFER_SIZE = 4800
# Уменьшенный размер очереди для каждого клиента
CLIENT_QUEUE_SIZE = 50
# Таймаут для keep-alive (увеличен для снижения нагрузки)
KEEP_ALIVE_TIMEOUT = 30.0
# Автоматическая очистка завершенных сессий (в секундах) - 20 минут
SESSION_CLEANUP_TIMEOUT = 1200.0


class Moment(BaseModel):
    monitor_id: str
    time_s: float
    real_time: str
    fhr_bpm: Optional[float] = None
    uterus_data: Optional[float] = None
    stop: int = 0


class Batch(BaseModel):
    kind: Literal["moments_batch"] = "moments_batch"
    monitor_id: str
    t_start: float
    t_end: float
    moments: List[Moment]
    warnings: List[str] = Field(default_factory=list)


class StatusRange(BaseModel):
    start: float
    end: float
    color_id: int


class Annotation(BaseModel):
    kind: Literal["annotation"] = "annotation"
    monitor_id: str
    t_start: float
    t_end: float
    annotation_type: str = "fast"
    fhr_line_status: List[StatusRange]
    fhr_event_status: List[StatusRange]
    toco_line_status: List[StatusRange]
    toco_tachysystole: List[StatusRange]
    toco_hypertonus: List[StatusRange]
    toco_tetanic: List[StatusRange]
    warnings: List[str] = Field(default_factory=list)


class SessionComplete(BaseModel):
    """Сообщение о завершении сессии"""
    kind: Literal["session_complete"] = "session_complete"
    monitor_id: str
    message: str = "Обработка данных завершена"


class MonitorSession:
    def __init__(self, monitor_id: str, fs: float, interval_sec: float, speed: float):
        self.monitor_id = monitor_id
        self.fs = fs
        self.interval_sec = interval_sec
        self.speed = speed
        self.created_at = datetime.now()

        self.time: Optional[np.ndarray] = None
        self.fhr: Optional[np.ndarray] = None
        self.uterus: Optional[np.ndarray] = None
        self.df_fhr: Optional[pd.DataFrame] = None
        self.df_uterus: Optional[pd.DataFrame] = None
        self.warnings_sorted: List[str] = []

        self.next_idx: int = 0
        self.points_per_batch: int = 1
        self.last_sent_second: float = 0.0
        self.done: bool = False
        self.done_event: asyncio.Event = asyncio.Event()
        

        self.message_buffer: deque = deque(maxlen=MESSAGE_BUFFER_SIZE)
        self.subscribers: List[asyncio.Queue] = []
        self.subscriber_lock = asyncio.Lock()
        
        self.history: List[Moment] = []

        # Двухуровневая система границ
        self.ann_last_t_end_fast: float = 0.0
        self.ann_last_t_end_full: float = 0.0
        self.ann_next_boundary_fast: float = ANNOTATION_FAST_PERIOD_SEC
        self.ann_next_boundary_full: float = ANNOTATION_FULL_PERIOD_SEC

        # Фоновые задачи
        self.processing_task: Optional[asyncio.Task] = None
        self.annotation_task: Optional[asyncio.Task] = None
        self.is_running: bool = False
        self.completion_sent: bool = False 
        
        # Статистика
        self.total_subscribers: int = 0
        self.current_subscribers: int = 0
        self.finished_at: Optional[datetime] = None
        
        # Предиктор гипоксии
        self.predictor = get_predictor()
        if self.predictor:
            self.predictor.reset()
            print(f"✓ Monitor {monitor_id}: Hypoxia predictor initialized (model loaded)")
        else:
            print(f"⚠ Monitor {monitor_id}: Hypoxia predictor unavailable (model not loaded)")

    def has_data(self) -> bool:
        return (
            self.time is not None
            and self.fhr is not None
            and self.uterus is not None
            and self.df_fhr is not None
            and self.df_uterus is not None
        )

    def get_current_data_time(self) -> float:
        """Возвращает максимальное время уже отправленных данных"""
        return float(self.last_sent_second)
    
    def is_truly_running(self) -> bool:
        """Проверяет, действительно ли монитор работает (не завершен)"""
        return self.is_running and not self.done
    
    async def add_subscriber(self, queue: asyncio.Queue):
        """Добавляет нового подписчика"""
        async with self.subscriber_lock:
            self.subscribers.append(queue)
            self.total_subscribers += 1
            self.current_subscribers = len(self.subscribers)
    
    async def remove_subscriber(self, queue: asyncio.Queue):
        """Удаляет подписчика"""
        async with self.subscriber_lock:
            try:
                self.subscribers.remove(queue)
            except ValueError:
                pass
            self.current_subscribers = len(self.subscribers)
    
    async def broadcast_message(self, message: Dict[str, Any]):
        """
        ОПТИМИЗАЦИЯ: Отправляет сообщение всем подписчикам через broadcast
        Использует буфер для новых подключений
        """
        self.message_buffer.append(message)
        
        async with self.subscriber_lock:
            dead_queues = []
            for q in self.subscribers:
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    dead_queues.append(q)
                except Exception:
                    dead_queues.append(q)
            
            for q in dead_queues:
                try:
                    self.subscribers.remove(q)
                except ValueError:
                    pass
            
            self.current_subscribers = len(self.subscribers)
    
    async def stop(self):
        """Останавливает все фоновые задачи"""
        if not self.is_running:
            return
            
        self.is_running = False
        self.done = True
        self.done_event.set()
        self.finished_at = datetime.now()
        
        if not self.completion_sent:
            completion_msg = SessionComplete(monitor_id=self.monitor_id)
            await self.broadcast_message(completion_msg.model_dump())
            self.completion_sent = True
        
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
        
        if self.annotation_task and not self.annotation_task.done():
            self.annotation_task.cancel()
            try:
                await self.annotation_task
            except asyncio.CancelledError:
                pass
        
        async with self.subscriber_lock:
            for q in self.subscribers:
                try:
                    q.put_nowait(None)
                except:
                    pass
            self.subscribers.clear()
            self.current_subscribers = 0


SESSIONS: Dict[str, MonitorSession] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    print("Сервер запускается...")
    
    cleanup_task = asyncio.create_task(_cleanup_finished_sessions())
    
    yield
    
    print("Останавливаем все фоновые задачи...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    for session in SESSIONS.values():
        await session.stop()
    print("Все задачи остановлены")


async def _cleanup_finished_sessions():
    """
    Фоновая задача для автоматической очистки завершенных сессий
    """
    while True:
        try:
            await asyncio.sleep(60.0) 
            
            now = datetime.now()
            to_remove = []
            
            for mid, session in SESSIONS.items():
                if (session.finished_at and 
                    (now - session.finished_at).total_seconds() > SESSION_CLEANUP_TIMEOUT and
                    session.current_subscribers == 0):
                    to_remove.append(mid)
            
            for mid in to_remove:
                print(f"Очистка завершенной сессии: {mid}")
                del SESSIONS[mid]
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Ошибка в _cleanup_finished_sessions: {e}")


app = FastAPI(
    title="КТГ Мониторинг API (v10.0)",
    version="10.0.0",
    description=(
        "КТГ Мониторинг API"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_csv_to_df(upload: UploadFile, fs: float) -> pd.DataFrame:
    try:
        df = pd.read_csv(upload.file)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Не удалось прочитать CSV '{upload.filename}': {e}"
        )

    if df.empty:
        raise HTTPException(status_code=400, detail=f"Пустой файл: {upload.filename}")

    if "value" not in df.columns:
        if df.shape[1] == 1:
            df = df.rename(columns={df.columns[0]: "value"})
        else:
            raise HTTPException(
                status_code=400,
                detail=f"'{upload.filename}' должен содержать столбец 'value' или один столбец.",
            )

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if df["value"].isna().all():
        raise HTTPException(
            status_code=400,
            detail=f"В '{upload.filename}' нет валидных числовых значений в 'value'.",
        )

    if "time_sec" in df.columns:
        df["time_sec"] = pd.to_numeric(df["time_sec"], errors="coerce")
        if df["time_sec"].isna().any():
            n = len(df)
            df["time_sec"] = np.arange(n) / float(fs)
    else:
        n = len(df)
        df["time_sec"] = np.arange(n) / float(fs)

    df = df.dropna(subset=["time_sec", "value"]).sort_values("time_sec").reset_index(drop=True)
    if df.empty:
        raise HTTPException(
            status_code=400, detail=f"После очистки в '{upload.filename}' не осталось данных."
        )

    return df[["time_sec", "value"]]


def _fmt_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _now() -> datetime:
    return datetime.now()


def _model_time_now(session: MonitorSession) -> float:
    elapsed_real = (_now() - session.created_at).total_seconds()
    return max(0.0, elapsed_real * max(0.1, session.speed))


def _subset_df_upto(df: pd.DataFrame, t_end: float) -> pd.DataFrame:
    """Отрезаем данные по времени <= t_end (включительно)."""
    return df.loc[df["time_sec"] <= (float(t_end) + 1e-9)].copy()


def _compress_status_ranges(t_arr: np.ndarray, status_arr: np.ndarray) -> List[StatusRange]:
    """Преобразует по-точечные статусы в интервалы [start,end] с color_id."""
    if t_arr is None or status_arr is None or len(t_arr) == 0:
        return []

    t = np.asarray(t_arr).astype(float)
    s = np.asarray(status_arr).astype(int)

    res: List[StatusRange] = []
    cur_val = int(s[0])
    seg_start = float(t[0])

    for i in range(1, len(s)):
        v = int(s[i])
        if v != cur_val:
            seg_end = float(t[i - 1])
            res.append(StatusRange(start=seg_start, end=seg_end, color_id=cur_val))
            seg_start = float(t[i])
            cur_val = v

    res.append(StatusRange(start=seg_start, end=float(t[-1]), color_id=cur_val))
    return res


def _merge_status_ranges(ranges: List[dict]) -> List[dict]:
    """Объединяет соседние сегменты с одинаковым color_id"""
    if not ranges:
        return []
    
    sorted_ranges = sorted(ranges, key=lambda r: r.get("start", 0))
    merged = [dict(sorted_ranges[0])]
    
    for curr in sorted_ranges[1:]:
        prev = merged[-1]
        if (curr.get("color_id") == prev.get("color_id") and 
            curr.get("start", 0) <= prev.get("end", 0) + 1.0):
            prev["end"] = max(prev.get("end", 0), curr.get("end", 0))
        else:
            merged.append(dict(curr))
    
    return merged


async def _processing_loop(session: MonitorSession):
    """
    ОПТИМИЗАЦИЯ: Основной цикл отправки RAW-точек с частотой 1 Гц (усреднение по секундам)
    Использует broadcast для отправки всем клиентам
    """
    try:
        if not session.has_data():
            return

        session.points_per_batch = max(1, int(round(session.interval_sec)))

        max_time_sec = int(session.time[-1])
        current_second = 0

        while session.is_running and current_second <= max_time_sec:
            try:
                model_time_now = _model_time_now(session)
                target_second = int(model_time_now)

                if target_second < current_second:
                    await asyncio.sleep(0.02)
                    continue

                end_second = min(current_second + session.points_per_batch, max_time_sec + 1)
                batch_moments = []

                for sec in range(current_second, end_second):
                    mask = (session.time >= sec) & (session.time < sec + 1)
                    indices = np.where(mask)[0]
                    
                    if len(indices) == 0:
                        continue
                    
                    avg_fhr = float(np.nanmean(session.fhr[indices]))
                    avg_uterus = float(np.nanmean(session.uterus[indices]))
                    
                    t_s = float(sec)
                    real_dt = session.created_at + timedelta(seconds=t_s / max(0.1, session.speed))
                    
                    batch_moments.append(
                        Moment(
                            monitor_id=session.monitor_id,
                            time_s=t_s,
                            real_time=_fmt_hhmm(real_dt),
                            fhr_bpm=avg_fhr if not np.isnan(avg_fhr) else None,
                            uterus_data=avg_uterus if not np.isnan(avg_uterus) else None,
                            stop=0,
                        )
                    )

                if batch_moments:
                    batch_moments[-1].stop = (1 if (end_second > max_time_sec) else 0)
                    batch = Batch(
                        monitor_id=session.monitor_id,
                        t_start=float(batch_moments[0].time_s),
                        t_end=float(batch_moments[-1].time_s),
                        moments=batch_moments,
                    )
                    
                    session.history.extend(batch.moments)
                    
                    await session.broadcast_message(batch.model_dump())
                    
                    session.last_sent_second = float(batch_moments[-1].time_s)

                current_second = end_second

                if current_second > max_time_sec:
                    await session.stop()
                    break

                await asyncio.sleep(0.02)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Ошибка в _processing_loop для {session.monitor_id}: {e}")
                await asyncio.sleep(0.1)
                
    except asyncio.CancelledError:
        pass
    finally:
        if not session.done:
            await session.stop()


async def _annotation_loop(session: MonitorSession):
    """
    ОПТИМИЗАЦИЯ: Цикл генерации аннотаций
    Использует broadcast для отправки всем клиентам
    """
    try:
        await asyncio.sleep(1.0)

        while session.is_running and not session.done:
            try:
                await asyncio.sleep(ANNOTATION_POLL_REAL_SEC)

                full_last_time = session.get_current_data_time()
                if full_last_time < 1e-3:
                    continue

                window_fast = ANNOTATION_FAST_PERIOD_SEC
                t_end_fast = min(session.ann_next_boundary_fast, full_last_time)
                reached_fast = (t_end_fast >= session.ann_next_boundary_fast - 1e-9)

                if reached_fast and (t_end_fast > session.ann_last_t_end_fast + 1e-9):
                    df_fhr_sub = _subset_df_upto(session.df_fhr, t_end_fast)
                    df_uter_sub = _subset_df_upto(session.df_uterus, t_end_fast)

                    if min(len(df_fhr_sub), len(df_uter_sub)) >= 2:
                        t_arr, _fhr, _uter, st, _ = compute_signals_and_statuses(
                            df_fhr_sub, df_uter_sub, fs=session.fs
                        )

                        ann_fast = Annotation(
                            monitor_id=session.monitor_id,
                            t_start=float(t_arr[0]),
                            t_end=float(t_arr[-1]),
                            annotation_type="fast",
                            fhr_line_status=_compress_status_ranges(t_arr, st["fhr_line_status"]),
                            fhr_event_status=_compress_status_ranges(t_arr, st["fhr_event_status"]),
                            toco_line_status=_compress_status_ranges(t_arr, st["toco_line_status"]),
                            toco_tachysystole=_compress_status_ranges(t_arr, st["toco_tachysystole"]),
                            toco_hypertonus=_compress_status_ranges(t_arr, st["toco_hypertonus"]),
                            toco_tetanic=_compress_status_ranges(t_arr, st["toco_tetanic"]),
                            warnings=[],
                        )

                        await session.broadcast_message(ann_fast.model_dump())
                        session.ann_last_t_end_fast = float(t_arr[-1])


                    if session.ann_next_boundary_fast < full_last_time - 1e-9:
                        session.ann_next_boundary_fast += window_fast


                window_full = ANNOTATION_FULL_PERIOD_SEC
                t_end_full = min(session.ann_next_boundary_full, full_last_time)
                reached_full = (t_end_full >= session.ann_next_boundary_full - 1e-9)

                if reached_full and (t_end_full > session.ann_last_t_end_full + 1e-9):
                    if full_last_time >= MIN_DATA_FOR_FULL_ANALYTICS_SEC:
                        df_fhr_sub = _subset_df_upto(session.df_fhr, t_end_full)
                        df_uter_sub = _subset_df_upto(session.df_uterus, t_end_full)

                        if min(len(df_fhr_sub), len(df_uter_sub)) >= 2:
                            t_arr, _fhr, _uter, st, warns_sorted = compute_signals_and_statuses(
                                df_fhr_sub, df_uter_sub, fs=session.fs
                            )
                            
                            hypoxia_warnings = []
                            if session.predictor:
                                try:
                                    result = session.predictor.predict(
                                        t_arr, _fhr, _uter, 
                                        current_time_sec=full_last_time
                                    )
                                    if result:
                                        prob, warning_text = result
                                        hypoxia_warnings.append(warning_text)
                                        print(f"HYPOXIA prediction: probability={prob*100:.1f}%, time={full_last_time:.0f}s")
                                    else:
                                        data_len = float(t_arr[-1] - t_arr[0]) if len(t_arr) > 0 else 0
                                        should = session.predictor.should_predict(full_last_time, data_len)
                                        print(f"HYPOXIA prediction skipped: data_len={data_len:.0f}s, should_predict={should}, last_pred={session.predictor.last_prediction_time:.0f}s")
                                except Exception as e:
                                    print(f"Ошибка предсказания гипоксии: {e}")
                                    import traceback
                                    traceback.print_exc()
                            else:
                                # Предиктор не инициализирован
                                if full_last_time > 1200 and session.ann_last_t_end_full < 60:  # Логируем только один раз
                                    print(f"HYPOXIA predictor not available (model not loaded)")
                            
                            # Объединяем все предупреждения
                            all_warnings = list(warns_sorted) if warns_sorted else []
                            all_warnings.extend(hypoxia_warnings)

                            ann_full = Annotation(
                                monitor_id=session.monitor_id,
                                t_start=float(t_arr[0]),
                                t_end=float(t_arr[-1]),
                                annotation_type="full",
                                fhr_line_status=_compress_status_ranges(t_arr, st["fhr_line_status"]),
                                fhr_event_status=_compress_status_ranges(t_arr, st["fhr_event_status"]),
                                toco_line_status=_compress_status_ranges(t_arr, st["toco_line_status"]),
                                toco_tachysystole=_compress_status_ranges(t_arr, st["toco_tachysystole"]),
                                toco_hypertonus=_compress_status_ranges(t_arr, st["toco_hypertonus"]),
                                toco_tetanic=_compress_status_ranges(t_arr, st["toco_tetanic"]),
                                warnings=all_warnings,
                            )
                            await session.broadcast_message(ann_full.model_dump())
                            session.ann_last_t_end_full = float(t_arr[-1])
                            
                            total_warnings = len(all_warnings)
                            regular_warnings = len(warns_sorted) if warns_sorted else 0
                            hypoxia_count = len(hypoxia_warnings)
                            print(f"📊 FULL annotation sent: t=0..{t_arr[-1]:.1f}s, warnings={total_warnings} (regular={regular_warnings}, hypoxia={hypoxia_count})")

                    if session.ann_next_boundary_full < full_last_time - 1e-9:
                        session.ann_next_boundary_full += window_full

                if session.done_event.is_set():
                    if session.ann_last_t_end_fast < full_last_time - 1e-9 or \
                       session.ann_last_t_end_full < full_last_time - 1e-9:
                        continue
                    break
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Ошибка в _annotation_loop для {session.monitor_id}: {e}")
                await asyncio.sleep(0.5)
                
    except asyncio.CancelledError:
        pass


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
def root():
    active_count = len([s for s in SESSIONS.values() if s.is_truly_running()])
    return {
        "name": "КТГ Мониторинг API",
        "version": "10.0.0",
        "status": "running",
        "active_sessions": active_count,
        "total_sessions": len(SESSIONS),
        "endpoints": {
            "upload": "POST /api/upload",
            "stream": "GET /api/stream/{monitor_id}",
            "monitors": "GET /api/monitors",
            "monitor_info": "GET /api/monitors/{monitor_id}",
            "stop_monitor": "POST /api/monitors/{monitor_id}/stop",
            "stop_all_monitors": "POST /api/monitors/stop-all",
            "instant": "POST /api/instant",
        },
        "improvements_v9": ["-"
        ],
    }


@app.get("/api/monitors")
def list_monitors():
    """Список всех мониторов с детальной информацией"""
    active = []
    finished = []
    
    for mid, session in SESSIONS.items():
        time_until_deletion = None
        if session.finished_at:
            elapsed = (datetime.now() - session.finished_at).total_seconds()
            time_until_deletion = max(0, SESSION_CLEANUP_TIMEOUT - elapsed)
        
        info = {
            "monitor_id": mid,
            "created_at": session.created_at.isoformat(),
            "finished_at": session.finished_at.isoformat() if session.finished_at else None,
            "time_until_deletion_sec": time_until_deletion,
            "speed": session.speed,
            "current_subscribers": session.current_subscribers,
            "total_subscribers_ever": session.total_subscribers,
            "current_time": session.get_current_data_time(),
            "total_duration": float(session.time[-1]) if session.time is not None else 0,
            "progress_percent": (
                (session.get_current_data_time() / float(session.time[-1]) * 100)
                if session.time is not None and session.time[-1] > 0
                else 0
            ),
        }
        
        if session.is_truly_running():
            active.append(info)
        else:
            finished.append(info)
    
    return {
        "active": active,
        "finished": finished,
        "total": len(SESSIONS),
    }


@app.get("/api/monitors/{monitor_id}")
def get_monitor_info(monitor_id: str = Path(...)):
    """Детальная информация о конкретном мониторе"""
    if monitor_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="monitor_id не найден")
    
    session = SESSIONS[monitor_id]

    time_until_deletion = None
    if session.finished_at:
        elapsed = (datetime.now() - session.finished_at).total_seconds()
        time_until_deletion = max(0, SESSION_CLEANUP_TIMEOUT - elapsed)
    
    return {
        "monitor_id": monitor_id,
        "created_at": session.created_at.isoformat(),
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "time_until_deletion_sec": time_until_deletion,
        "is_running": session.is_running,
        "is_truly_running": session.is_truly_running(),
        "is_done": session.done,
        "speed": session.speed,
        "fs": session.fs,
        "interval_sec": session.interval_sec,
        "current_subscribers": session.current_subscribers,
        "total_subscribers_ever": session.total_subscribers,
        "history_length": len(session.history),
        "current_time": session.get_current_data_time(),
        "total_duration": float(session.time[-1]) if session.time is not None else 0,
        "progress_percent": (
            (session.get_current_data_time() / float(session.time[-1]) * 100)
            if session.time is not None and session.time[-1] > 0
            else 0
        ),
        "next_idx": session.next_idx,
        "total_points": len(session.time) if session.time is not None else 0,
    }


@app.post("/api/monitors/{monitor_id}/stop")
async def stop_monitor(monitor_id: str = Path(...)):
    """Остановить конкретный монитор"""
    if monitor_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="monitor_id не найден")
    
    session = SESSIONS[monitor_id]
    await session.stop()
    
    return {
        "monitor_id": monitor_id,
        "status": "stopped",
        "message": "Монитор успешно остановлен",
    }


@app.post("/api/monitors/stop-all")
async def stop_all_monitors():
    """
    НОВОЕ: Остановить все активные мониторы
    """
    stopped_count = 0
    stopped_ids = []
    
    for mid, session in list(SESSIONS.items()):
        if session.is_truly_running():
            await session.stop()
            stopped_count += 1
            stopped_ids.append(mid)
    
    return {
        "status": "success",
        "message": f"Остановлено {stopped_count} мониторов",
        "stopped_count": stopped_count,
        "stopped_monitor_ids": stopped_ids,
        "remaining_sessions": len(SESSIONS) - stopped_count,
    }


@app.post("/api/upload")
async def upload_and_start(
    fhr_file: UploadFile = File(..., description="CSV с ЧСС (value[, time_sec])"),
    uterus_file: UploadFile = File(..., description="CSV с маткой (value[, time_sec])"),
    monitor_id: Optional[str] = Query(None, description="Явный ID монитора"),
    interval_sec: float = Query(1.0, ge=0.1, le=10.0, description="Период батча сырья, сек"),
    fs: float = Query(FS_DEFAULT, gt=0.0, description="Частота дискретизации"),
    speed: float = Query(1.0, ge=0.1, le=100.0, description="Ускорение модельного времени"),
):
    """
    Запускает фоновую обработку с двухуровневой системой аннотаций.
    Можно подключаться с множества устройств к одному monitor_id.
    """
    mid = monitor_id or str(uuid.uuid4())

    if mid in SESSIONS:
        existing_session = SESSIONS[mid]
        if existing_session.is_truly_running():
            raise HTTPException(
                status_code=409,
                detail=f"monitor_id '{mid}' уже активен. Используйте GET /api/stream/{mid} для подключения.",
            )
        else:
            del SESSIONS[mid]


    bpm_df = _read_csv_to_df(fhr_file, fs)
    uter_df = _read_csv_to_df(uterus_file, fs)

    if min(len(bpm_df), len(uter_df)) < 10:
        raise HTTPException(status_code=400, detail="Слишком мало данных")

    time_arr, fhr, uterus, _statuses, warnings_sorted = compute_signals_and_statuses(
        bpm_df,        
        uter_df,      
        fs=fs
    )

    session = MonitorSession(mid, fs, interval_sec, speed)
    session.time = time_arr
    session.fhr = fhr
    session.uterus = uterus
    session.df_fhr = bpm_df
    session.df_uterus = uter_df
    session.warnings_sorted = list(warnings_sorted) if warnings_sorted else []
    session.is_running = True

    SESSIONS[mid] = session


    session.processing_task = asyncio.create_task(_processing_loop(session))
    session.annotation_task = asyncio.create_task(_annotation_loop(session))

    return {
        "monitor_id": mid,
        "status": "started",
        "points": int(time_arr.shape[0]),
        "duration_sec": float(time_arr[-1]),
        "interval_sec": interval_sec,
        "speed": speed,
        "data_frequency": "1 Hz (averaged)",
        "annotation_fast_period_sec": ANNOTATION_FAST_PERIOD_SEC,
        "annotation_full_period_sec": ANNOTATION_FULL_PERIOD_SEC,
        "stream_url": f"/api/stream/{mid}",
        "monitor_info_url": f"/api/monitors/{mid}",
        "message": "Фоновая обработка запущена. Данные передаются с частотой 1 Гц (усредненные значения). Подключайтесь к stream_url с любого количества устройств.",
    }


@app.get("/api/stream/{monitor_id}")
async def connect_stream(monitor_id: str = Path(..., description="ID монитора")):
    if monitor_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="monitor_id не найден")

    session = SESSIONS[monitor_id]

    q: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)
    await session.add_subscriber(q)

    async def event_gen():
        try:
            if session.message_buffer:
                for msg in session.message_buffer:
                    payload = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {payload}\n\n"
            
            if not session.is_truly_running():
                completion_msg = SessionComplete(monitor_id=session.monitor_id)
                payload = json.dumps(completion_msg.model_dump(), ensure_ascii=False, separators=(",", ":"))
                yield f"data: {payload}\n\n"
                return

            while True:
                try:

                    data = await asyncio.wait_for(q.get(), timeout=KEEP_ALIVE_TIMEOUT)
                    
                    if data is None:
                        break
                    
                    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {payload}\n\n"
                    
                except asyncio.TimeoutError:
                    if not session.is_truly_running():
                        if not session.completion_sent:
                            completion_msg = SessionComplete(monitor_id=session.monitor_id)
                            payload = json.dumps(completion_msg.model_dump(), ensure_ascii=False, separators=(",", ":"))
                            yield f"data: {payload}\n\n"
                            session.completion_sent = True
                        break

                    yield ": keep-alive\n\n"
                    
        except asyncio.CancelledError:

            pass
        except Exception as e:
            print(f"Ошибка в event_gen для {monitor_id}: {e}")
        finally:
            await session.remove_subscriber(q)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    }

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers=headers,
    )


@app.get("/api/monitors/{monitor_id}/report")
async def get_monitor_report(monitor_id: str = Path(..., description="ID монитора")):
    """
    Получение полной расшифровки и анализа завершенной записи мониторинга.
    Возвращает историю разметки и текстовую интерпретацию данных.
    """
    if monitor_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Монитор с указанным ID не найден")
    
    session = SESSIONS[monitor_id]

    if not session.done:
        raise HTTPException(
            status_code=400, 
            detail="Монитор еще работает. Расшифровка доступна только для завершенных записей."
        )

    annotations_history = []
    for msg in session.message_buffer:
        if msg.get("kind") == "annotation":
            annotations_history.append(msg)
    

    text_report = _generate_text_report(session, annotations_history)
    
    return {
        "monitor_id": monitor_id,
        "status": "completed",
        "duration_sec": float(session.time[-1]) if session.time is not None else 0,
        "completed_at": session.finished_at.isoformat() if session.finished_at else None,
        "annotations_count": len(annotations_history),
        "annotations_history": annotations_history,
        "text_report": text_report,
    }


def _generate_instant_text_report(
    monitor_id: str,
    duration_sec: float,
    annotations: List[Dict[str, Any]],
    warnings: List[str]
) -> str:
    """
    Генерация детального текстового отчета в стиле report_generator.py
    с разбивкой по 30-минутным интервалам.
    """
    
    def _fmt_hhmm(t_sec: float) -> str:
        """Форматирование времени в HH:MM"""
        t = max(0.0, float(t_sec))
        m = int(t // 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}"
    
    def _fmt_min(sec: float) -> str:
        """Форматирование секунд в минуты"""
        return f"{sec/60:.1f} мин"
    
    def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
        """Вычисление пересечения двух временных интервалов"""
        return max(0.0, min(a1, b1) - max(a0, b0))
    
    lines = []
    lines.append("=" * 80)
    lines.append("ОТЧЕТ ПО ЗАПИСИ КТГ (интервалы по 30 минут, отсчет от 00:00)")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"ID записи: {monitor_id}")
    lines.append(f"Длительность записи: {duration_sec:.1f} с ({duration_sec/60:.1f} мин)")
    lines.append(f"Дата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # Критические предупреждения
    if warnings:
        lines.append("-" * 80)
        lines.append("КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:")
        lines.append("-" * 80)
        for i, warning in enumerate(warnings, 1):
            lines.append(f"{i}. {warning}")
        lines.append("")
    
    interval_sec = 30 * 60  # 30 минут
    n_intervals = int(np.ceil(duration_sec / interval_sec))
    
    if annotations and n_intervals > 0:
        for k in range(n_intervals):
            t0 = k * interval_sec
            t1 = min(duration_sec, (k + 1) * interval_sec)
            
            lines.append(f"{_fmt_hhmm(t0)}–{_fmt_hhmm(t1)}")
            
            # Находим аннотации, попадающие в этот интервал
            interval_anns = []
            for ann in annotations:
                ann_start = ann.get("t_start", 0)
                ann_end = ann.get("t_end", 0)
                if _overlap(t0, t1, ann_start, ann_end) > 0:
                    interval_anns.append(ann)
            
            if not interval_anns:
                lines.append("  • Данные отсутствуют")
                lines.append("")
                continue
            
            # Объединяем данные из всех аннотаций в интервале
            all_fhr_line = []
            all_fhr_events = []
            all_toco_line = []
            all_toco_tachy = []
            all_toco_hyper = []
            all_toco_tetanic = []
            interval_warnings = []
            
            for ann in interval_anns:
                all_fhr_line.extend(ann.get("fhr_line_status", []))
                all_fhr_events.extend(ann.get("fhr_event_status", []))
                all_toco_line.extend(ann.get("toco_line_status", []))
                all_toco_tachy.extend(ann.get("toco_tachysystole", []))
                all_toco_hyper.extend(ann.get("toco_hypertonus", []))
                all_toco_tetanic.extend(ann.get("toco_tetanic", []))
                interval_warnings.extend(ann.get("warnings", []))
            
            # Анализ ЧСС
            fhr_parts = []
            
            # Определяем цветовые коды для состояний
            fhr_color_ids = [r.get("color_id", 0) for r in all_fhr_line]
            
            # Базовая информация о ЧСС
            fhr_parts.append("база в пределах нормы")
            
            # Анализ патологий ЧСС
            if 3 in fhr_color_ids or 2 in fhr_color_ids:
                # Считаем длительность патологических состояний
                total_pathology = sum(r.get("end", 0) - r.get("start", 0) 
                                    for r in all_fhr_line 
                                    if r.get("color_id", 0) in [2, 3])
                if total_pathology > 0:
                    if 3 in fhr_color_ids:
                        fhr_parts.append(f"критические отклонения {_fmt_min(total_pathology)}")
                    elif 2 in fhr_color_ids:
                        fhr_parts.append(f"значимые отклонения {_fmt_min(total_pathology)}")
            
            if fhr_parts:
                lines.append("- ЧСС: " + "; ".join(fhr_parts) + ".")
            
            # Анализ акцелераций/децелераций
            merged_fhr_events = _merge_status_ranges(all_fhr_events)
            event_color_ids = [r.get("color_id", 0) for r in merged_fhr_events]
            if merged_fhr_events:
                accel_count = sum(1 for r in merged_fhr_events if r.get("color_id", 0) == 0)
                decel_count = sum(1 for r in merged_fhr_events if r.get("color_id", 0) > 0)
                
                if accel_count > 0:
                    lines.append(f"- Акцелерации: {accel_count}.")
                
                if decel_count > 0:
                    decel_parts = [f"{decel_count}"]
                    if 3 in event_color_ids:
                        decel_parts.append("патологические")
                    elif 2 in event_color_ids:
                        decel_parts.append("поздние/вариабельные")
                    elif 1 in event_color_ids:
                        decel_parts.append("ранние")
                    lines.append(f"- Децелерации: {' ('.join(decel_parts)}{')'if len(decel_parts)>1 else ''}.")
            
            # Анализ маточной активности
            merged_toco_line = _merge_status_ranges(all_toco_line)
            contractions_count = len([r for r in merged_toco_line if r.get("color_id", 0) > 0])

            
            if contractions_count > 0 or all_toco_tachy or all_toco_hyper or all_toco_tetanic:
                interval_duration = t1 - t0
                toco_parts = []
                
                if contractions_count > 0:
                    rate_per_10 = (contractions_count / interval_duration * 600.0) if interval_duration > 0 else 0.0
                    toco_head = f"- Схватки: {contractions_count} за {interval_duration/60:.0f} мин"
                    toco_parts.append(f"~{rate_per_10:.1f}/10 мин")
                
                # Патологические состояния
                flags = []
                if all_toco_tachy:
                    flags.append("тахисистолия")
                if all_toco_hyper:
                    flags.append("гипертонус")
                if all_toco_tetanic:
                    tetanic_count = len(all_toco_tetanic)
                    flags.append(f"тетанические: {tetanic_count}")
                
                if flags:
                    toco_parts.append(", ".join(flags))
                
                if contractions_count > 0:
                    if toco_parts:
                        lines.append(toco_head + " (" + "; ".join(toco_parts) + ").")
                    else:
                        lines.append(toco_head + ".")
                elif toco_parts:
                    lines.append("- Маточная активность: " + "; ".join(toco_parts) + ".")
            
            # Предупреждения в интервале
            if interval_warnings:
                unique_warnings = list(set(interval_warnings))
                lines.append(f"- Предупреждения: {len(unique_warnings)}")
                for w in unique_warnings[:3]:  # Показываем до 3 предупреждений
                    lines.append(f"  • {w}")
                if len(unique_warnings) > 3:
                    lines.append(f"  • ... и еще {len(unique_warnings) - 3}")
            
            lines.append("")
    else:
        lines.append("Аннотации отсутствуют или запись слишком короткая для анализа.")
        lines.append("")
    
    # Заключение
    lines.append("-" * 80)
    lines.append("ЗАКЛЮЧЕНИЕ:")
    lines.append("-" * 80)
    lines.append(_generate_instant_conclusion(warnings, annotations))
    lines.append("")
    lines.append("=" * 80)
    lines.append("ВНИМАНИЕ: Это автоматическая интерпретация. Окончательное решение")
    lines.append("принимает врач на основании полной клинической картины.")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def _generate_instant_conclusion(warnings: List[str], annotations: List[Dict[str, Any]]) -> str:
    """Генерация итогового заключения для instant режима"""
    if warnings:
        critical_count = len(warnings)
        return (
            f"ТРЕБУЕТСЯ ВНИМАНИЕ: Обнаружено {critical_count} критических предупреждений.\n"
            "Рекомендуется немедленная консультация врача и возможное\n"
            "инструментальное вмешательство для уточнения состояния плода."
        )
    
    pathology_count = 0
    for ann in annotations:
        color_ids = []
        for key in ["fhr_line_status", "fhr_event_status", "toco_line_status"]:
            ranges = ann.get(key, [])
            color_ids.extend([r.get("color_id") for r in ranges])
        
        if 3 in color_ids or 2 in color_ids:
            pathology_count += 1
    
    if pathology_count > len(annotations) * 0.3 if annotations else False:
        return (
            "⚡ УМЕРЕННЫЙ РИСК: Обнаружены периоды с отклонениями от нормы.\n"
            "Рекомендуется продолжить мониторинг и наблюдение.\n"
            "При ухудшении показателей - консультация врача."
        )
    
    return (
        "✓ СОСТОЯНИЕ УДОВЛЕТВОРИТЕЛЬНОЕ: Показатели КТГ в целом в пределах нормы.\n"
        "Продолжить плановое наблюдение согласно протоколу.\n"
        "Рекомендуется повторное КТГ согласно графику."
    )


def _generate_text_report(session: MonitorSession, annotations: List[Dict[str, Any]]) -> str:
    """
    Генерация текстовой расшифровки записи КТГ в стиле report_generator.py
    с разбивкой по 30-минутным интервалам.
    """
    
    def _fmt_hhmm(t_sec: float) -> str:
        """Форматирование времени в HH:MM"""
        t = max(0.0, float(t_sec))
        m = int(t // 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}"
    
    def _fmt_min(sec: float) -> str:
        """Форматирование секунд в минуты"""
        return f"{sec/60:.1f} мин"
    
    def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
        """Вычисление пересечения двух временных интервалов"""
        return max(0.0, min(a1, b1) - max(a0, b0))
    
    lines = []
    lines.append("=" * 80)
    lines.append("ОТЧЕТ ПО ЗАПИСИ КТГ (интервалы по 30 минут, отсчет от 00:00)")
    lines.append("=" * 80)
    lines.append("")
    
    # Базовая информация
    duration = float(session.time[-1]) if session.time is not None else 0
    lines.append(f"ID записи: {session.monitor_id}")
    lines.append(f"Продолжительность: {duration:.1f} секунд ({duration/60:.1f} минут)")
    lines.append(f"Дата завершения: {session.finished_at.strftime('%Y-%m-%d %H:%M:%S') if session.finished_at else 'Неизвестно'}")
    lines.append("")
    
    # Анализ предупреждений
    if session.warnings_sorted:
        lines.append("-" * 80)
        lines.append("КРИТИЧЕСКИЕ ПРЕДУПРЕЖДЕНИЯ:")
        lines.append("-" * 80)
        for i, warning in enumerate(session.warnings_sorted, 1):
            lines.append(f"{i}. {warning}")
        lines.append("")
    
    # Детализация по 30-минутным интервалам
    interval_sec = 30 * 60  # 30 минут
    n_intervals = int(np.ceil(duration / interval_sec))
    
    if annotations and n_intervals > 0:
        for k in range(n_intervals):
            t0 = k * interval_sec
            t1 = min(duration, (k + 1) * interval_sec)
            
            lines.append(f"{_fmt_hhmm(t0)}–{_fmt_hhmm(t1)}")
            
            # Находим аннотации, попадающие в этот интервал
            interval_anns = []
            for ann in annotations:
                ann_start = ann.get("t_start", 0)
                ann_end = ann.get("t_end", 0)
                if _overlap(t0, t1, ann_start, ann_end) > 0:
                    interval_anns.append(ann)
            
            if not interval_anns:
                lines.append("  • Данные отсутствуют")
                lines.append("")
                continue
            
            # Объединяем данные из всех аннотаций в интервале
            all_fhr_line = []
            all_fhr_events = []
            all_toco_line = []
            all_toco_tachy = []
            all_toco_hyper = []
            all_toco_tetanic = []
            interval_warnings = []
            
            for ann in interval_anns:
                all_fhr_line.extend(ann.get("fhr_line_status", []))
                all_fhr_events.extend(ann.get("fhr_event_status", []))
                all_toco_line.extend(ann.get("toco_line_status", []))
                all_toco_tachy.extend(ann.get("toco_tachysystole", []))
                all_toco_hyper.extend(ann.get("toco_hypertonus", []))
                all_toco_tetanic.extend(ann.get("toco_tetanic", []))
                interval_warnings.extend(ann.get("warnings", []))
            
            # Анализ ЧСС
            fhr_parts = []
            
            # Определяем цветовые коды для состояний
            fhr_color_ids = [r.get("color_id", 0) for r in all_fhr_line]
            
            # Базовая информация о ЧСС
            fhr_parts.append("база в пределах нормы")
            
            # Анализ патологий ЧСС
            if 3 in fhr_color_ids or 2 in fhr_color_ids:
                # Считаем длительность патологических состояний
                total_pathology = sum(r.get("end", 0) - r.get("start", 0) 
                                    for r in all_fhr_line 
                                    if r.get("color_id", 0) in [2, 3])
                if total_pathology > 0:
                    if 3 in fhr_color_ids:
                        fhr_parts.append(f"критические отклонения {_fmt_min(total_pathology)}")
                    elif 2 in fhr_color_ids:
                        fhr_parts.append(f"значимые отклонения {_fmt_min(total_pathology)}")
            
            if fhr_parts:
                lines.append("- ЧСС: " + "; ".join(fhr_parts) + ".")
            
            # Анализ акцелераций/децелераций
            merged_fhr_events = _merge_status_ranges(all_fhr_events)
            event_color_ids = [r.get("color_id", 0) for r in merged_fhr_events]
            if merged_fhr_events:
                accel_count = sum(1 for r in merged_fhr_events if r.get("color_id", 0) == 0)
                decel_count = sum(1 for r in merged_fhr_events if r.get("color_id", 0) > 0)
                
                if accel_count > 0:
                    lines.append(f"- Акцелерации: {accel_count}.")
                
                if decel_count > 0:
                    decel_parts = [f"{decel_count}"]
                    if 3 in event_color_ids:
                        decel_parts.append("патологические")
                    elif 2 in event_color_ids:
                        decel_parts.append("поздние/вариабельные")
                    elif 1 in event_color_ids:
                        decel_parts.append("ранние")
                    lines.append(f"- Децелерации: {' ('.join(decel_parts)}{')'if len(decel_parts)>1 else ''}.")
            
            # Анализ маточной активности
            merged_toco_line = _merge_status_ranges(all_toco_line)
            contractions_count = len([r for r in merged_toco_line if r.get("color_id", 0) > 0])

            
            if contractions_count > 0 or all_toco_tachy or all_toco_hyper or all_toco_tetanic:
                interval_duration = t1 - t0
                toco_parts = []
                
                if contractions_count > 0:
                    rate_per_10 = (contractions_count / interval_duration * 600.0) if interval_duration > 0 else 0.0
                    toco_head = f"- Схватки: {contractions_count} за {interval_duration/60:.0f} мин"
                    toco_parts.append(f"~{rate_per_10:.1f}/10 мин")
                
                # Патологические состояния
                flags = []
                if all_toco_tachy:
                    flags.append("тахисистолия")
                if all_toco_hyper:
                    flags.append("гипертонус")
                if all_toco_tetanic:
                    tetanic_count = len(all_toco_tetanic)
                    flags.append(f"тетанические: {tetanic_count}")
                
                if flags:
                    toco_parts.append(", ".join(flags))
                
                if contractions_count > 0:
                    if toco_parts:
                        lines.append(toco_head + " (" + "; ".join(toco_parts) + ").")
                    else:
                        lines.append(toco_head + ".")
                elif toco_parts:
                    lines.append("- Маточная активность: " + "; ".join(toco_parts) + ".")
            
            # Предупреждения в интервале
            if interval_warnings:
                unique_warnings = list(set(interval_warnings))
                lines.append(f"- Предупреждения: {len(unique_warnings)}")
                for w in unique_warnings[:3]:  # Показываем до 3 предупреждений
                    lines.append(f"  • {w}")
                if len(unique_warnings) > 3:
                    lines.append(f"  • ... и еще {len(unique_warnings) - 3}")
            
            lines.append("")
    else:
        lines.append("Аннотации отсутствуют")
        lines.append("")
    
    # Заключение
    lines.append("-" * 80)
    lines.append("ЗАКЛЮЧЕНИЕ:")
    lines.append("-" * 80)
    lines.append(_generate_conclusion(session, annotations))
    lines.append("")
    lines.append("=" * 80)
    lines.append("ВНИМАНИЕ: Это автоматическая интерпретация. Окончательное решение")
    lines.append("принимает врач на основании полной клинической картины.")
    lines.append("=" * 80)
    
    return "\n".join(lines)


def _interpret_fhr_line_status(ranges: List[Dict]) -> str:
    """Интерпретация статуса базовой линии ЧСС"""
    if not ranges:
        return "Нормальная вариабельность"
    
    color_ids = [r.get("color_id") for r in ranges]
    
    # Цветовая схема: 0-норма, 1-внимание, 2-тревога, 3-критично
    if 3 in color_ids:
        return "КРИТИЧНО: Обнаружены патологические паттерны (брадикардия/тахикардия)"
    elif 2 in color_ids:
        return "ТРЕВОГА: Значительные отклонения от нормы"
    elif 1 in color_ids:
        return "ВНИМАНИЕ: Незначительные отклонения, требуется наблюдение"
    return "✓ Базовая линия в норме"


def _interpret_fhr_event_status(ranges: List[Dict]) -> str:
    """Интерпретация событий ЧСС (акцелерации/децелерации)"""
    if not ranges:
        return "События не обнаружены"
    
    color_ids = [r.get("color_id") for r in ranges]
    
    if 3 in color_ids:
        return "КРИТИЧНО: Патологические децелерации"
    elif 2 in color_ids:
        return "ТРЕВОГА: Поздние или вариабельные децелерации"
    elif 1 in color_ids:
        return "ВНИМАНИЕ: Ранние децелерации или снижение вариабельности"
    return "Акцелерации в пределах нормы"


def _interpret_toco_status(ranges: List[Dict]) -> str:
    """Интерпретация базовой маточной активности"""
    if not ranges:
        return "Отсутствует или минимальная"
    
    color_ids = [r.get("color_id") for r in ranges]
    
    if 3 in color_ids:
        return "Патологический паттерн"
    elif 2 in color_ids:
        return "Повышенная активность"
    return "Нормальная активность"


def _interpret_pathology_ranges(ranges: List[Dict], found_text: str) -> str:
    """Интерпретация патологических состояний"""
    if not ranges:
        return "не обнаружено"
    
    total_duration = sum(r.get("end", 0) - r.get("start", 0) for r in ranges)
    count = len(ranges)
    
    return f"{found_text} ({count} эпизод(ов), общая длительность: {total_duration:.1f}с)"


def _generate_conclusion(session: MonitorSession, annotations: List[Dict]) -> str:
    """Генерация итогового заключения (заглушка)"""
    if session.warnings_sorted:
        critical_count = len(session.warnings_sorted)
        return (
            f"ТРЕБУЕТСЯ ВНИМАНИЕ: Обнаружено {critical_count} критических предупреждений.\n"
            "Рекомендуется немедленная консультация врача и возможное\n"
            "инструментальное вмешательство для уточнения состояния плода."
        )
    
    # Подсчет патологических периодов
    pathology_count = 0
    for ann in annotations:
        color_ids = []
        for key in ["fhr_line_status", "fhr_event_status", "toco_line_status"]:
            ranges = ann.get(key, [])
            color_ids.extend([r.get("color_id") for r in ranges])
        
        if 3 in color_ids or 2 in color_ids:
            pathology_count += 1
    
    if pathology_count > len(annotations) * 0.3:
        return (
            "УМЕРЕННЫЙ РИСК: Обнаружены периоды с отклонениями от нормы.\n"
            "Рекомендуется продолжить мониторинг и наблюдение.\n"
            "При ухудшении показателей - консультация врача."
        )
    
    return (
        "СОСТОЯНИЕ УДОВЛЕТВОРИТЕЛЬНОЕ: Показатели КТГ в целом в пределах нормы.\n"
        "Продолжить плановое наблюдение согласно протоколу.\n"
        "Рекомендуется повторное КТГ согласно графику."
    )


@app.post("/api/instant")
async def instant(
    fhr_file: UploadFile = File(..., description="CSV с ЧСС"),
    uterus_file: UploadFile = File(..., description="CSV с маткой"),
    monitor_id: Optional[str] = Query(None),
    fs: float = Query(FS_DEFAULT, gt=0.0),
    interval_sec: float = Query(1.0, ge=0.1, le=10.0),
    speed: float = Query(1.0, ge=0.1, le=100.0),
):
    """Мгновенная обработка без фоновых задач (для быстрого анализа) с частотой 1 Гц"""
    mid = monitor_id or str(uuid.uuid4())

    bpm_df = _read_csv_to_df(fhr_file, fs)
    uter_df = _read_csv_to_df(uterus_file, fs)

    time_arr_full, fhr_full, uter_full, _st_full, _ = compute_signals_and_statuses(
        bpm_df,           # данные ЧСС
        uter_df,       # данные ТОКО
        fs=fs
    )
 
    created_at = _now()
    moments: List[Dict[str, Any]] = []

    max_time_sec = int(time_arr_full[-1])
    
    for sec in range(max_time_sec + 1):

        mask = (time_arr_full >= sec) & (time_arr_full < sec + 1)
        indices = np.where(mask)[0]
        
        if len(indices) == 0:
            continue

        avg_fhr = float(np.nanmean(fhr_full[indices]))
        avg_uterus = float(np.nanmean(uter_full[indices]))
        
        t_s = float(sec)
        real_dt = created_at + timedelta(seconds=t_s / max(0.1, speed))
        
        moments.append(
            {
                "monitor_id": mid,
                "time_s": t_s,
                "real_time": _fmt_hhmm(real_dt),
                "fhr_bpm": avg_fhr if not np.isnan(avg_fhr) else None,
                "uterus_data": avg_uterus if not np.isnan(avg_uterus) else None,
                "stop": 0,
            }
        )

    if moments:
        moments[-1]["stop"] = 1

    total = float(time_arr_full[-1])
    annotations: List[Dict[str, Any]] = []
    all_warnings: List[str] = []

    df_fhr_sub = _subset_df_upto(bpm_df, total)
    df_uter_sub = _subset_df_upto(uter_df, total)

    if min(len(df_fhr_sub), len(df_uter_sub)) >= 2:
        t_arr, _fhr, _uter, st, warns_sorted = compute_signals_and_statuses(
            df_fhr_sub, df_uter_sub, fs=fs
        )
        
        all_warnings = list(warns_sorted) if warns_sorted else []

        ann = Annotation(
            monitor_id=mid,
            t_start=float(t_arr[0]),
            t_end=float(t_arr[-1]),
            annotation_type="full",
            fhr_line_status=_compress_status_ranges(t_arr, st["fhr_line_status"]),
            fhr_event_status=_compress_status_ranges(t_arr, st["fhr_event_status"]),
            toco_line_status=_compress_status_ranges(t_arr, st["toco_line_status"]),
            toco_tachysystole=_compress_status_ranges(t_arr, st["toco_tachysystole"]),
            toco_hypertonus=_compress_status_ranges(t_arr, st["toco_hypertonus"]),
            toco_tetanic=_compress_status_ranges(t_arr, st["toco_tetanic"]),
            warnings=all_warnings,
        )
        annotations = [ann.model_dump()]

    text_report = _generate_instant_text_report(
        monitor_id=mid,
        duration_sec=total,
        annotations=annotations,
        warnings=all_warnings
    )

    return {
        "monitor_id": mid,
        "duration_sec": total,
        "moments": moments,
        "annotations": annotations,
        "annotation_mode": "instant_full",
        "text_report": text_report,
    }


if __name__ == "__main__":
    uvicorn.run(
        "api_server_optimized:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        log_level="info",
    )