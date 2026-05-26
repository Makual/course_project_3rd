from typing import Dict, List, Tuple, Any
import numpy as np
import pandas as pd

# ————————————————————————————————————————————————————————————————
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ————————————————————————————————————————————————————————————————

def _interp_nans(x: np.ndarray) -> np.ndarray:
    y = np.asarray(x, dtype=float).ravel().copy()
    n = y.size
    if n == 0:
        return y
    mask = np.isnan(y)
    if not mask.any():
        return y
    idx = np.arange(n, dtype=float)
    y[mask] = np.interp(idx[mask], idx[~mask], y[~mask])
    return y

def _moving_avg(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float).ravel()
    w = max(1, int(w))
    if w <= 1 or x.size == 0:
        return x.copy()
    k = np.ones(w, float)
    s = np.convolve(x, k, "same")
    c = np.convolve(np.ones_like(x), k, "same")
    return s / np.maximum(c, 1e-9)

def _rolling_median(x: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(x, dtype=float).ravel()
    w = max(1, int(w))
    if w == 1 or x.size < w:
        return x.copy()
    from numpy.lib.stride_tricks import sliding_window_view
    sw = sliding_window_view(x, w)
    med = np.median(sw, axis=-1)
    pad_l = w // 2
    pad_r = w - 1 - pad_l
    return np.pad(med, (pad_l, pad_r), mode="edge")

def _hampel(x: np.ndarray, w: int, n_sigmas: float = 3.0) -> np.ndarray:
    """
    Классический фильтр Hampel: заменяет выбросы на локальную медиану.
    w — нечётное окно в пробах.
    """
    x = np.asarray(x, dtype=float).ravel()
    w = max(3, int(w) | 1)
    if x.size == 0:
        return x.copy()
    from numpy.lib.stride_tricks import sliding_window_view
    sw = sliding_window_view(x, w)
    med = np.median(sw, axis=-1)
    mad = np.median(np.abs(sw - med[:, None]), axis=-1)
    pad_l = w // 2
    pad_r = w - 1 - pad_l
    med_f = np.pad(med, (pad_l, pad_r), mode="edge")
    mad_f = np.pad(mad, (pad_l, pad_r), mode="edge")
    thresh = n_sigmas * 1.4826 * np.maximum(mad_f, 1e-9)
    y = x.copy()
    outliers = np.abs(y - med_f) > thresh
    y[outliers] = med_f[outliers]
    return y

def _segments_from_mask(mask: np.ndarray) -> List[tuple]:
    mask = np.asarray(mask, dtype=bool).ravel()
    if mask.size == 0:
        return []
    diff = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e > s]

def _merge_segments(segs: List[tuple], max_gap: int) -> List[tuple]:
    if not segs:
        return []
    segs = sorted(segs)
    res = [segs[0]]
    for s, e in segs[1:]:
        ps, pe = res[-1]
        if s - pe <= max_gap:
            res[-1] = (ps, max(pe, e))
        else:
            res.append((s, e))
    return res

def _filter_by_len_and_peak(delta: np.ndarray, segs: List[tuple],
                            min_len: int, min_peak: float, kind: str) -> List[tuple]:
    out = []
    for s, e in segs:
        if e - s < min_len:
            continue
        seg = delta[s:e]
        if seg.size == 0:
            continue
        peak = float(np.max(seg) if kind == "accel" else -np.min(seg))
        if peak >= float(min_peak):
            out.append((int(s), int(e)))
    return out

def _hysteresis_mask(delta: np.ndarray, enter_thr: float, exit_thr: float, sign: int) -> np.ndarray:
    """
    sign = +1 для акцелераций, -1 для децелераций
    """
    assert sign in (+1, -1)
    x = sign * np.asarray(delta, float).ravel()
    m = np.zeros_like(x, dtype=bool)
    on = False
    for i, v in enumerate(x):
        if not on and v >= enter_thr:
            on = True
        if on:
            m[i] = True
            if v < exit_thr:
                on = False
    return m

def _align_len(*arrs: np.ndarray) -> Tuple[np.ndarray, ...]:
    if not arrs:
        return tuple()
    m = min(len(a) for a in arrs)
    return tuple(a[:m] for a in arrs)

# ————————————————————————————————————————————————————————————————
# АНАЛИЗ ТОКОГРАММЫ
# ————————————————————————————————————————————————————————————————

def _extract_contractions(uterus: np.ndarray, fs: float) -> Tuple[np.ndarray, np.ndarray, List[tuple]]:
    """
    Возвращает:
      tone — оценка «тонуса» (скользящая медиана)
      excess — превышение над тоном (>=0)
      contr — список сегментов схваток (индексы), критерии: excess>=10 условных единиц, длительность >=30 с,
              допускается «хвост» смыкания разрывов до ~12 с.
    """
    x = _interp_nans(np.asarray(uterus, float).ravel())
    xs = _moving_avg(x, max(1, int(round(fs * 3.0))))
    tone = _rolling_median(xs, max(1, int(round(fs * 75.0))))  # ~75 с для медленного дрейфа
    excess = np.maximum(xs - tone, 0.0)

    thr = 10.0
    raw = _segments_from_mask(excess >= thr)
    # смыкаем близкие отрезки
    gap_close = int(round(fs * 12.0))
    merged: List[tuple] = []
    if raw:
        cs, ce = raw[0]
        for s, e in raw[1:]:
            if s - ce <= gap_close:
                ce = e
            else:
                merged.append((cs, ce))
                cs, ce = s, e
        merged.append((cs, ce))
    min_len = int(round(fs * 30.0))
    contr = [(s, e) for s, e in merged if (e - s) >= min_len]
    return tone, excess, contr

def _tachysystole_mask_from_contractions(n: int, contr: List[tuple], fs: float) -> np.ndarray:
    """
    Маска тахисистолии: >5 схваток за 10 минут.
    Формируем покадрово, проходя окна 10 мин со сдвигом 60 с.
    """
    mask = np.zeros(n, dtype=int)
    L = int(round(600.0 * fs))   # 10 мин
    S = int(round(60.0 * fs))    # шаг 60 с
    starts = list(range(0, max(1, n - L + 1), S)) or [0]
    contr_s = np.array([s for s, _ in contr], int)
    contr_e = np.array([e for _, e in contr], int)
    for s0 in starts:
        e0 = min(n, s0 + L)
        if contr:
            # считаем схватки, пересекающие окно (по сегментам, а не по пикам)
            cnt = int(np.sum((contr_s < e0) & (contr_e > s0)))
        else:
            cnt = 0
        if cnt > 5:
            mask[s0:e0] = 1
    return mask

def _hypertonus_mask(n: int, tone: np.ndarray, fs: float) -> np.ndarray:
    """
    Маска гипертонуса: медиана «тонуса» >25 условных единиц. на окнах 10 мин.
    """
    mask = np.zeros(n, dtype=int)
    L = int(round(600.0 * fs))
    S = int(round(60.0 * fs))
    starts = list(range(0, max(1, n - L + 1), S)) or [0]
    for s0 in starts:
        e0 = min(n, s0 + L)
        if e0 > s0 and float(np.median(tone[s0:e0])) > 25.0:
            mask[s0:e0] = 1
    return mask

def _tetany_mask(n: int, contr: List[tuple], fs: float) -> np.ndarray:
    """
    Тетания: любая схватка длительностью ≥120 с.
    """
    mask = np.zeros(n, dtype=int)
    thr_len = int(round(120.0 * fs))
    for s, e in contr:
        if (e - s) >= thr_len:
            mask[s:e] = 1
    return mask

# ————————————————————————————————————————————————————————————————
# КЛАССИФИКАЦИЯ FHR
# ————————————————————————————————————————————————————————————————

def _classify_fhr_states(
    fhr: np.ndarray,
    fs: float,
    *,
    smooth_seconds: float = 5.0,
    hampel_seconds: float = 3.0,
    baseline_seconds: float = 120.0,     # 10 минут для базальной линии
    severe_brady_threshold: float = 100.0,
    brady_threshold: float = 120.0,      # КЛЮЧЕВОЕ: <120 — брадикардия (по спецификации)
    tachy_threshold: float = 160.0,
    severe_tachy_threshold: float = 180.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Возвращает:
      states         — коды -2..2 (брадикардия/тахикардия по УСТОЙЧИВОЙ базальной линии)
      baseline_stable — устойчивая база (сглаженное среднее) для классификации состояний
      baseline_event — локальная базальная линия (робастная медиана) для детекции событий
      x_smooth       — сглаженный и «очищенный» ряд (для детекции событий)
    
    Согласно спецификации:
    - Устойчивая база = сглаженное среднее по окну ≥10 мин → для классификации состояний
    - Локальная база = скользящая медиана по окну ≈10 мин → для событий (акц/дец)
    """
    x = _interp_nans(np.asarray(fhr, dtype=float).ravel())
    n = x.size

    # Сглаживание + Hampel
    smooth_win = max(1, int(round(fs * smooth_seconds)))
    x_smooth = _moving_avg(x, smooth_win)
    x_smooth = _hampel(x_smooth, max(3, int(round(fs * hampel_seconds)) | 1))

    base_win = max(1, int(round(fs * baseline_seconds)))
    
    # УСТОЙЧИВАЯ БАЗА (сглаженное среднее) — для классификации состояний -2..2
    baseline_stable = _moving_avg(x_smooth, base_win)
    
    # ЛОКАЛЬНАЯ БАЗА (медиана) — для детекции событий (акцелерации/децелерации)
    baseline_event = _rolling_median(x_smooth, base_win)

    # Выравнивание длин ПЕРЕД индексацией
    baseline_stable = baseline_stable[:n]
    baseline_event = baseline_event[:n]
    x_smooth = x_smooth[:n]

    # Коды состояний по УСТОЙЧИВОЙ БАЗЕ (не по локальной!)
    states = np.zeros_like(baseline_stable, dtype=int)
    states[baseline_stable < brady_threshold] = -1
    states[baseline_stable < severe_brady_threshold] = -2
    states[baseline_stable > tachy_threshold] = 1
    states[baseline_stable > severe_tachy_threshold] = 2

    return states, baseline_stable, baseline_event, x_smooth

# ————————————————————————————————————————————————————————————————
# ОСНОВНОЙ ПАЙПЛАЙН
# ————————————————————————————————————————————————————————————————

STATE_LABELS: Dict[int, str] = {
    0: "Норма",
    -1: "Базальная брадикардия",
    -2: "Тяжёлая базальная брадикардия",
    1: "Базальная тахикардия",
    2: "Тяжёлая базальная тахикардия",
}

def compute_signals_and_statuses(
    bpm_df: pd.DataFrame,
    uterus_df: pd.DataFrame,
    fs: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any], List[str]]:
    """
    Выравнивает длины входов/промежуточных рядов, считает статусы на КАЖДОЙ точке.
    Возвращает:
      time_s, fhr, uterus,
      statuses: dict (линии статусов + события + коды состояний -2..2 + СТАТИСТИКА),
      warnings_sorted: List[str]
    """
    # Пустые
    if min(len(bpm_df), len(uterus_df)) <= 0:
        empty_f = np.array([], dtype=float)
        empty_i = np.array([], dtype=int)
        statistics = {STATE_LABELS[k]: 0.0 for k in STATE_LABELS}
        statistics["Всего, сек"] = 0.0
        statuses = {
            "fhr_line_status": empty_i,
            "fhr_event_status": empty_i,
            "fhr_states": empty_i,
            "toco_line_status": empty_i,
            "toco_tachysystole": empty_i,
            "toco_hypertonus": empty_i,
            "toco_tetanic": empty_i,
            "fhr_statistics": statistics,
            "baseline_stable": empty_f,
            "baseline_event": empty_f,
        }
        return empty_f, empty_f, empty_f, statuses, ["Нет данных"]

    n0 = min(len(bpm_df), len(uterus_df))
    bpm_df = bpm_df.iloc[:n0].reset_index(drop=True)
    uterus_df = uterus_df.iloc[:n0].reset_index(drop=True)

    time_s = bpm_df["time_sec"].values.astype(float, copy=False)
    fhr = bpm_df["value"].values.astype(float, copy=False)
    uterus = uterus_df["value"].values.astype(float, copy=False)

    # Классификация состояний и базальная линия
    states, baseline_stable, baseline_ev, x_smooth = _classify_fhr_states(fhr, fs)

    # Выравнивание
    time_s, fhr, uterus, states, baseline_stable, baseline_ev, x_smooth = _align_len(
        time_s, fhr, uterus, states, baseline_stable, baseline_ev, x_smooth
    )
    n = len(time_s)

    # Линия FHR «по состояниям»
    fhr_line = states.astype(int, copy=False)

    # Детекция акцел/децел относительно БАЗАЛЬНОЙ линии (delta)
    delta = x_smooth - baseline_ev
    accel_mask0 = _hysteresis_mask(delta, enter_thr=12.0, exit_thr=8.0, sign=+1)
    decel_mask0 = _hysteresis_mask(delta, enter_thr=12.0, exit_thr=8.0, sign=-1)

    merge_gap = int(round(fs * 5.0))
    accel_segs = _merge_segments(_segments_from_mask(accel_mask0), merge_gap)
    decel_segs = _merge_segments(_segments_from_mask(decel_mask0), merge_gap)

    min_len_acc = int(round(fs * 15.0))
    min_len_dec = int(round(fs * 15.0))
    accel_segs = _filter_by_len_and_peak(delta, accel_segs, min_len_acc, 15.0, "accel")
    decel_segs = _filter_by_len_and_peak(delta, decel_segs, min_len_dec, 15.0, "decel")

    # Код событий по времени (1 = акцелерация, -1 = децелерация)
    fhr_evt = np.zeros(n, dtype=int)
    for s, e in accel_segs:
        fhr_evt[s:e] = 1
    for s, e in decel_segs:
        fhr_evt[s:e] = -1

    # ТОКО: тонус/схватки → тахисистолия/гипертонус/тетания
    tone, excess, contr = _extract_contractions(uterus, fs)
    toco_tachy = _tachysystole_mask_from_contractions(n, contr, fs)
    toco_hyper = _hypertonus_mask(n, tone, fs)
    toco_tet = _tetany_mask(n, contr, fs)

    # Интенсивность (для визуальной «линии»): превышение над тоном
    intensity = np.maximum(excess, 0.0)
    # «Грубая» линейка интенсивности для статуса в каждой точке (0/1/2)
    toco_line = np.array([2 if v > 80.0 else (1 if v >= 30.0 else 0) for v in intensity], dtype=int)

    # Статистика FHR по времени
    statistics: Dict[str, float] = {STATE_LABELS[s]: float(np.sum(states == s) / fs) for s in STATE_LABELS}
    statistics["Всего, сек"] = float(n / fs)

    # Кол-во «пробегов» по состояниям (смены состояний)
    if n > 0:
        cp = np.flatnonzero(np.diff(states)) + 1
        seg_starts = np.r_[0, cp]
        seg_states = states[seg_starts]
    else:
        seg_states = np.array([], dtype=int)
    for s in (-2, -1, 1, 2):
        statistics[f"Промежутки (шт) — {STATE_LABELS[s]}"] = float(int(np.sum(seg_states == s)))
    statistics["Промежутки (шт) — Не норма (всего)"] = float(int(np.sum(seg_states != 0)))

    # Доп. статистика по событиям
    def _dur(segs: List[tuple]) -> float:
        return sum((e - s) for s, e in segs) / fs

    def _amps(segs: List[tuple], kind: str) -> List[float]:
        vals: List[float] = []
        for s, e in segs:
            seg = delta[max(0, s):min(n, e)]
            if seg.size == 0:
                continue
            vals.append(float(np.max(seg) if kind == "accel" else -np.min(seg)))
        return vals

    acc_durs = [(min(n, e) - max(0, s)) / fs for s, e in accel_segs if min(n, e) > max(0, s)]
    dec_durs = [(min(n, e) - max(0, s)) / fs for s, e in decel_segs if min(n, e) > max(0, s)]
    acc_amps = _amps(accel_segs, "accel")
    dec_deps = _amps(decel_segs, "decel")

    statistics.update({
        "Акселерации — всего, сек": float(_dur(accel_segs)),
        "Акселерации — эпизоды (шт)": float(len(accel_segs)),
        "Акселерации — медиана длительности, сек": float(np.median(acc_durs) if acc_durs else 0.0),
        "Акселерации — макс амплитуда, уд/мин": float(max(acc_amps) if acc_amps else 0.0),

        "Децелерации — всего, сек": float(_dur(decel_segs)),
        "Децелерации — эпизоды (шт)": float(len(decel_segs)),
        "Децелерации — медиана длительности, сек": float(np.median(dec_durs) if dec_durs else 0.0),
        "Децелерации — макс глубина, уд/мин": float(max(dec_deps) if dec_deps else 0.0),

        "Децелерации — пролонгированные >2 мин (шт)": float(sum(d > 120.0 for d in dec_durs)),
        "Децелерации — ≥5 мин (шт)": float(sum(d >= 300.0 for d in dec_durs)),
    })

    statuses: Dict[str, Any] = {
        "fhr_line_status": fhr_line.astype(int, copy=False),
        "fhr_event_status": fhr_evt.astype(int, copy=False),
        "fhr_states": states.astype(int, copy=False),
        "toco_line_status": toco_line.astype(int, copy=False),
        "toco_tachysystole": toco_tachy.astype(int, copy=False),
        "toco_hypertonus": toco_hyper.astype(int, copy=False),
        "toco_tetanic": toco_tet.astype(int, copy=False),
        "fhr_statistics": statistics,
        "baseline_stable": baseline_stable.astype(float, copy=False),
        "baseline_event": baseline_ev.astype(float, copy=False),
    }

    warnings_sorted = generate_warnings(
        fhr=fhr, uterus=uterus, fs=fs,
        fhr_line=fhr_line, fhr_event=fhr_evt,
        toco_line=toco_line, toco_tachy=toco_tachy,
        toco_hyper=toco_hyper, toco_tet=toco_tet
    )

    return time_s, fhr, uterus, statuses, warnings_sorted

# ————————————————————————————————————————————————————————————————
# ПРЕДУПРЕЖДЕНИЯ
# ————————————————————————————————————————————————————————————————

def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return (min(a1, b1) - max(a0, b0)) > 0.0

def generate_warnings(
    *,
    fhr: np.ndarray,
    uterus: np.ndarray,
    fs: float,
    fhr_line: np.ndarray,
    fhr_event: np.ndarray,
    toco_line: np.ndarray,
    toco_tachy: np.ndarray,
    toco_hyper: np.ndarray,
    toco_tet: np.ndarray,
) -> List[str]:
    # Подготовка FHR
    x = _interp_nans(np.asarray(fhr, float).ravel())
    smooth = _moving_avg(x, max(1, int(round(fs * 5.0))))
    smooth = _hampel(smooth, max(3, int(round(fs * 3.0)) | 1))
    base = _rolling_median(smooth, max(1, int(round(fs * 120.0))))  # 10 мин
    delta = smooth - base
    n = len(smooth)

    # Децелерации (как в основном пайплайне)
    dec_mask0 = _hysteresis_mask(delta, enter_thr=12.0, exit_thr=8.0, sign=-1)
    dec_segs = _merge_segments(_segments_from_mask(dec_mask0), int(round(fs * 5.0)))
    dec_segs = _filter_by_len_and_peak(delta, dec_segs, int(round(fs * 15.0)), 15.0, "decel")
    dec_segs_s = [(s / fs, e / fs) for s, e in dec_segs]
    dec_long_warn = [(s, e) for (s, e) in dec_segs_s if (e - s) > 120.0]  # >2 мин (для «длительные»)
    dec_long_crit = [(s, e) for (s, e) in dec_segs_s if (e - s) >= 180.0]  # ≥3 мин — КРИТИЧНО

    # Базальная брадикардия (≥10 мин) - ИСПРАВЛЕНО по спецификации: <120 (не <110)
    base_brady = (base < 120.0).astype(int)
    base_sev_brady = (base < 100.0).astype(int)
    def _max_run_len(mask01: np.ndarray) -> float:
        max_len = 0
        cur = 0
        for v in mask01:
            if v:
                cur += 1
                max_len = max(max_len, cur)
            else:
                cur = 0
        return max_len / fs
    base_brady_10m = _max_run_len(base_brady) >= 120.0
    base_sev_brady_10m = _max_run_len(base_sev_brady) >= 120.0

    # ТОКО: восстановим тонус/схватки, окна и маски
    tone, excess, contr = _extract_contractions(uterus, fs)
    toco_tachy_mask = _tachysystole_mask_from_contractions(n, contr, fs)  # >5/10мин
    toco_hyper_mask = _hypertonus_mask(n, tone, fs)
    toco_tet_mask = _tetany_mask(n, contr, fs)

    # Вспомогательные структуры
    contr_s = np.array([s / fs for s, e in contr]) if contr else np.array([], float)
    contr_e = np.array([e / fs for s, e in contr]) if contr else np.array([], float)

    def ratio_decels_per_contr(t0: float, t1: float) -> float:
        if contr_s.size == 0:
            return 0.0
        idx = np.where((contr_s < t1) & (contr_e > t0))[0]
        if idx.size == 0:
            return 0.0
        coupled = 0
        for k in idx:
            c0, c1 = float(contr_s[k]), float(contr_e[k])
            if any(_overlap(c0, c1, d0, d1) for (d0, d1) in dec_segs_s):
                coupled += 1
        return coupled / float(idx.size)

    def tachysystole_recent(t: float, horizon_s: float = 1800.0) -> bool:
        # Тахисистолия, пересекающая окно [t-horizon, t]
        a0, a1 = max(0.0, t - horizon_s), t
        L = int(round(600.0 * fs))
        S = int(round(60.0 * fs))
        starts = list(range(0, max(1, n - L + 1), S)) or [0]
        for s0 in starts:
            e0 = min(n, s0 + L)
            if (s0 / fs) < a1 and (e0 / fs) > a0:
                if np.any(toco_tachy_mask[s0:e0] == 1):
                    return True
        return False

    def hyper_overlap(t0: float, t1: float) -> bool:
        L = int(round(600.0 * fs))
        S = int(round(60.0 * fs))
        starts = list(range(0, max(1, n - L + 1), S)) or [0]
        for s0 in starts:
            e0 = min(n, s0 + L)
            if (t0 < e0 / fs) and (t1 > s0 / fs) and np.any(toco_hyper_mask[s0:e0] == 1):
                return True
        return False

    def no_recovery_between_contractions(t0: float, t1: float) -> bool:
        if contr_s.size < 2:
            return False
        idx = np.where((contr_s >= t0) & (contr_e <= t1))[0]
        if idx.size < 2:
            return False
        for i in range(idx.size - 1):
            e1 = contr_e[idx[i]]
            s2 = contr_s[idx[i + 1]]
            lo = int(max(0, np.floor(e1 * fs)))
            hi = int(min(len(smooth), np.ceil(s2 * fs)))
            if hi > lo and np.min(smooth[lo:hi]) < 120.0:
                return True
            for (d0, d1) in dec_segs_s:
                if _overlap(e1, s2, d0, d1):
                    return True
        return False


    texts: list[tuple[int, str]] = []

    # 1) Критические базальные вещи
    if base_sev_brady_10m:
        texts.append((0, "КРИТИЧНО: Тяжёлая базальная брадикардия <100 уд/мин ≥10 мин"))
    elif base_brady_10m:
        texts.append((3, "Базальная брадикардия <120 уд/мин ≥10 мин"))

    # 2) Пролонгированная децелерация
    if dec_long_crit:
        texts.append((0, "Пролонгированная децелерация ≥3 мин"))

    # 3) Тетания/гипертонус + падение ЧСС/децелерации
    tetany_segs = _segments_from_mask(toco_tet_mask == 1)
    for s, e in tetany_segs:
        u0, u1 = s / fs, e / fs
        # падение ЧСС <120 или перекрытие с децелерациями, или гипертонус
        lo, hi = int(max(0, np.floor(u0 * fs))), int(min(n, np.ceil(u1 * fs)))
        fhr_drop = (hi > lo) and (np.min(smooth[lo:hi]) < 120.0)
        dec_overlap = any(_overlap(u0, u1, d0, d1) for (d0, d1) in dec_segs_s)
        if fhr_drop or dec_overlap or hyper_overlap(u0, u1):
            texts.append((1, "Тетания/гипертонус + падение ЧСС/децелерации"))
            break

    # 4) Связь децелераций со схватками: 20-мин окна, шаг 60 с
    T_total = n / fs
    win = 1200.0
    step = 60.0
    seen_64 = False
    seen_65_crit = False
    seen_65_warn = False
    t = 0.0
    while t < T_total:
        w0, w1 = t, min(t + win, T_total)
        ratio = ratio_decels_per_contr(w0, w1)
        if ratio >= 0.5 and not seen_64 and tachysystole_recent(w1, 1800.0):
            texts.append((1, "Тахисистолия (последние 30 мин) + децелерации в ≥50% схваток (20 мин)"))
            seen_64 = True
        if ratio >= 0.5:
            # Доп. критерии «нет восстановления» или «длительные децелерации»
            no_rec = no_recovery_between_contractions(w0, w1)
            long_present = any(_overlap(w0, w1, s, e) for (s, e) in dec_long_warn)
            if (no_rec or long_present) and not seen_65_crit:
                texts.append((2, "≥50% децелераций + (нет восстановления или длительные >2 мин)"))
                seen_65_crit = True
            elif not seen_65_warn and not (no_rec or long_present):
                texts.append((4, "Децелерации в ≥50% схваток (20 мин)"))
                seen_65_warn = True
        t += step


    if not texts:
        return []

    texts.sort(key=lambda x: x[0])
    out: List[str] = []
    seen_critical: set = set()
    seen_warning: set = set()
    
    for priority, text in texts:
        is_critical = "КРИТИЧНО" in text
        
        alert_key = text.split(":", 1)[1].strip() if ":" in text else text
        
        if is_critical:
            if alert_key not in seen_critical and text not in out:
                out.append(text)
                seen_critical.add(alert_key)
        else:
            if alert_key not in seen_warning and text not in out:
                out.append(text)
                seen_warning.add(alert_key)
    
    return out if out else []