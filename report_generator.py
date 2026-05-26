from typing import Any, Dict, List
import numpy as np

def build_report_from_outputs(
    fhr_bpm: np.ndarray,
    fhr_fs: float,
    states: np.ndarray,
    baseline_event: np.ndarray,
    toco_fs: float,
    contractions: List[Dict],
    windows_alerts: List[Dict],
    alerts_result: Dict[str, Any],
    *,
    interval_minutes: float = 30.0,

    smooth_seconds_fhr: float = 5.0,
    hampel_seconds_fhr: float = 3.0,
    accel_enter: float = 12.0, accel_exit: float = 8.0,
    decel_enter: float = 12.0, decel_exit: float = 8.0,
    accel_min_seconds: float = 15.0, decel_min_seconds: float = 15.0,
    accel_min_peak: float = 15.0, decel_min_depth: float = 15.0,
    merge_gap_seconds: float = 5.0,
) -> Dict[str, Any]:

    # ---------- утилиты ----------
    def _fmt_hhmm(t_sec: float) -> str:
        t = max(0.0, float(t_sec))
        m = int(t // 60); h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}"

    def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
        return max(0.0, min(a1, b1) - max(a0, b0))

    def _moving_avg(x: np.ndarray, win_samples: int) -> np.ndarray:
        if win_samples < 1: return x.copy()
        k = np.ones(win_samples, float)
        s = np.convolve(x, k, "same")
        c = np.convolve(np.ones_like(x), k, "same")
        return s / np.maximum(c, 1e-9)

    def _hampel(y: np.ndarray, win_samples: int = 21, n_sigmas: float = 3.0) -> np.ndarray:
        w = int(max(3, win_samples | 1))
        if y.size < w: return y.copy()
        from numpy.lib.stride_tricks import sliding_window_view
        sw = sliding_window_view(y, w)
        med = np.median(sw, axis=-1)
        mad = np.median(np.abs(sw - med[..., None]), axis=-1)
        sigma = 1.4826 * mad
        pad_left = w // 2; pad_right = w - 1 - pad_left
        med = np.pad(med, (pad_left, pad_right), mode="edge")
        sigma = np.pad(sigma, (pad_left, pad_right), mode="edge")
        out = y.copy(); mask = np.abs(out - med) > n_sigmas * (sigma + 1e-9)
        out[mask] = med[mask]
        return out

    def _segments_from_mask(mask: np.ndarray) -> List[tuple]:
        diff = np.diff(mask.astype(np.int8), prepend=0, append=0)
        starts = np.flatnonzero(diff == 1); ends = np.flatnonzero(diff == -1)
        return list(zip(starts, ends))

    def _merge_segments(segs: List[tuple], max_gap: int) -> List[tuple]:
        if not segs: return []
        segs.sort(); res = [segs[0]]
        for s, e in segs[1:]:
            ps, pe = res[-1]
            if s - pe <= max_gap: res[-1] = (ps, max(pe, e))
            else: res.append((s, e))
        return res

    def _filter_by_len_and_peak(delta: np.ndarray, segs: List[tuple],
                                min_len: int, min_peak: float, kind: str) -> List[tuple]:
        out = []
        for s, e in segs:
            if e - s < min_len: continue
            seg = delta[s:e]
            peak = float(np.max(seg) if kind == "accel" else -np.min(seg))
            if peak >= min_peak: out.append((s, e))
        return out

    def _hysteresis_mask(delta: np.ndarray, enter_thr: float, exit_thr: float, sign: int) -> np.ndarray:
        x = sign * delta
        m = np.zeros_like(x, dtype=bool); on = False
        for i, v in enumerate(x):
            if not on and v >= enter_thr: on = True
            if on:
                m[i] = True
                if v < exit_thr: on = False
        return m


    # ---------- проверки ----------
    x = np.asarray(fhr_bpm, float).ravel()
    n = x.size
    if n == 0: raise ValueError("Пустой ряд fhr_bpm.")
    if states.shape[0] != n: raise ValueError("Длина states должна совпадать с fhr_bpm.")
    if baseline_event.shape[0] != n: raise ValueError("Длина baseline_event должна совпадать с fhr_bpm.")

    T = n / float(fhr_fs)
    interval_s = float(interval_minutes) * 60.0
    n_intervals = int(np.ceil(T / interval_s))

    # ---------- сглаживание ЧСС и delta ----------
    smooth_win = max(1, int(round(fhr_fs * smooth_seconds_fhr)))
    x_smooth = _moving_avg(x, smooth_win)
    x_smooth = _hampel(x_smooth, max(3, int(fhr_fs * hampel_seconds_fhr) | 1))
    delta = x_smooth - baseline_event

    # ---------- эпизоды акцелераций/децелераций ----------
    merge_gap = int(round(fhr_fs * merge_gap_seconds))
    min_len_acc = int(round(fhr_fs * accel_min_seconds))
    min_len_dec = int(round(fhr_fs * decel_min_seconds))

    accel_mask0 = _hysteresis_mask(delta, accel_enter, accel_exit, sign=+1)
    decel_mask0 = _hysteresis_mask(delta, decel_enter, decel_exit, sign=-1)
    accel_segs_idx = _merge_segments(_segments_from_mask(accel_mask0), merge_gap)
    decel_segs_idx = _merge_segments(_segments_from_mask(decel_mask0), merge_gap)
    accel_segs_idx = _filter_by_len_and_peak(delta, accel_segs_idx, min_len_acc, accel_min_peak, "accel")
    decel_segs_idx = _filter_by_len_and_peak(delta, decel_segs_idx, min_len_dec, decel_min_depth, "decel")

    def _segs_stats(segs_idx: List[tuple], kind: str) -> List[Dict]:
        out = []
        for s, e in segs_idx:
            seg_delta = delta[s:e]
            if seg_delta.size == 0: continue
            amp = float(np.max(seg_delta) if kind == "accel" else -np.min(seg_delta))
            out.append({
                "start_s": s / float(fhr_fs),
                "end_s":   e / float(fhr_fs),
                "duration_s": (e - s) / float(fhr_fs),
                "amp_bpm": amp,
            })
        return out

    accels = _segs_stats(accel_segs_idx, "accel")
    decels = _segs_stats(decel_segs_idx, "decel")

    # ---------- предупреждения ----------
    alerts = list(alerts_result.get("alerts", [])) if isinstance(alerts_result, dict) else []

    # ---------- агрегация по интервалам ----------
    intervals: List[Dict[str, Any]] = []
    for k in range(n_intervals):
        t0 = k * interval_s
        t1 = min(T, (k + 1) * interval_s)
        i0 = int(np.floor(t0 * fhr_fs))
        i1 = int(np.ceil(t1 * fhr_fs)); i1 = min(n, max(i1, i0 + 1))
        dur = t1 - t0

        # длительности состояний
        st = states[i0:i1]
        d_norm = float(np.sum(st == 1) / fhr_fs)
        d_bm   = float(np.sum(st == 2) / fhr_fs)
        d_bs   = float(np.sum(st == 3) / fhr_fs)
        d_tm   = float(np.sum(st == 4) / fhr_fs)
        d_ts   = float(np.sum(st == 5) / fhr_fs)

        # базальная линия (локальная) в интервале
        base_med = float(np.median(baseline_event[i0:i1]))
        base_min = float(np.min(baseline_event[i0:i1]))
        base_max = float(np.max(baseline_event[i0:i1]))

        # эпизоды в окне
        def _in_window(episodes: List[Dict]):
            out = []
            for ep in episodes:
                s0, s1 = float(ep["start_s"]), float(ep["end_s"])
                if _overlap(t0, t1, s0, s1) > 0: out.append(ep)
            return out

        acc_eps = _in_window(accels)
        dec_eps = _in_window(decels)

        long_dec = [e for e in dec_eps if e["duration_s"] > 90.0]
        very_long_dec = [e for e in dec_eps if e["duration_s"] >= 180.0]

        # маточная активность (схватки)
        cont_eps = _in_window(contractions)
        n_cont = len(cont_eps)
        rate_per_10 = (n_cont / dur * 600.0) if (dur > 0 and n_cont > 0) else 0.0
        med_cont_dur = float(np.median([c["duration_s"] for c in cont_eps]) if cont_eps else 0.0)
        tetanic_cnt = sum(1 for c in cont_eps if c.get("duration_s", 0.0) >= 120.0)


        mvu_vals: List[float] = []
        bin_k0 = int(t0 // 600.0)
        bin_k1 = int(t1 // 600.0)  
        for b in range(bin_k0, bin_k1):
            w0, w1 = b * 600.0, (b + 1) * 600.0
            s = 0.0
            for c in cont_eps:
                pk = float(c.get("peak_s", c["start_s"]))
                if w0 <= pk < w1:
                    s += float(c.get("amp_rel", 0.0)) 
            mvu_vals.append(s)
        mvu_median = float(np.median(mvu_vals)) if mvu_vals else 0.0
        mvu_min = float(np.min(mvu_vals)) if mvu_vals else 0.0
        mvu_max = float(np.max(mvu_vals)) if mvu_vals else 0.0

        # окна тахисистолии/гипертонуса
        def _win(label: str) -> bool:
            for w in windows_alerts or []:
                if w.get("label") == label and _overlap(t0, t1, float(w["start_s"]), float(w["end_s"])) > 0:
                    return True
            return False
        has_tachysystole = _win("Тахисистолия")
        has_hypertonus   = _win("Гипертонус")

        # предупреждения в интервале
        a_in = []
        for a in alerts:
            a0 = float(a.get("t_start", 0.0))
            a1 = float(a.get("t_end")) if a.get("t_end") is not None else a0
            if _overlap(t0, t1, a0, a1 if a1 > a0 else a0 + 1e-6) > 0:
                a_in.append(a)

        intervals.append({
            "t0_s": float(t0), "t1_s": float(t1),
            "label": f"{_fmt_hhmm(t0)}–{_fmt_hhmm(t1)}",
            "fhr": {
                "baseline_median_bpm": base_med,
                "baseline_range_bpm": (base_min, base_max),
                "durations_sec": {
                    "norm": d_norm,
                    "brady_moderate": d_bm,
                    "brady_severe": d_bs,
                    "tachy_moderate": d_tm,
                    "tachy_severe": d_ts,
                },
                "accels": {
                    "count": len(acc_eps),
                    "median_duration_s": float(np.median([e["duration_s"] for e in acc_eps]) if acc_eps else 0.0),
                    "max_amp_bpm": float(max([e["amp_bpm"] for e in acc_eps]) if acc_eps else 0.0),
                },
                "decels": {
                    "count": len(dec_eps),
                    "median_duration_s": float(np.median([e["duration_s"] for e in dec_eps]) if dec_eps else 0.0),
                    "max_depth_bpm": float(max([e["amp_bpm"] for e in dec_eps]) if dec_eps else 0.0),
                    "long_over_90s": len(long_dec),
                    "prolonged_over_180s": len(very_long_dec),
                },
            },
            "toco": {
                "contractions_count": n_cont,
                "rate_per_10min": rate_per_10,
                "median_duration_s": med_cont_dur,
                "mvu_per_10min_median": mvu_median,
                "mvu_per_10min_range": (mvu_min, mvu_max),
                "tachysystole": bool(has_tachysystole),
                "hypertonus": bool(has_hypertonus),
                "tetanic_count": int(tetanic_cnt),
            },
            "alerts": a_in,
        })

    def _fmt_min(sec: float) -> str:
        return f"{sec/60:.1f} мин"

    lines = ["ОТЧЕТ ПО ЗАПИСИ (интервалы по 30 минут, отсчет от 00:00)\n"]
    for r in intervals:
        lines.append(r["label"])

        base = r["fhr"]; d = base["durations_sec"]
        parts = [f"база {base['baseline_median_bpm']:.0f} уд/мин (диапазон {base['baseline_range_bpm'][0]:.0f}–{base['baseline_range_bpm'][1]:.0f})"]

        tach_total = d["tachy_moderate"] + d["tachy_severe"]
        if tach_total > 0:
            comps = []
            if d["tachy_moderate"] > 0: comps.append(f"умер. {_fmt_min(d['tachy_moderate'])}")
            if d["tachy_severe"]  > 0: comps.append(f"тяж. {_fmt_min(d['tachy_severe'])}")
            parts.append(f"тахикардия: {_fmt_min(tach_total)}" + (f" ({'; '.join(comps)})" if comps else ""))


        brad_total = d["brady_moderate"] + d["brady_severe"]
        if brad_total > 0:
            comps = []
            if d["brady_moderate"] > 0: comps.append(f"умер. {_fmt_min(d['brady_moderate'])}")
            if d["brady_severe"]  > 0: comps.append(f"тяж. {_fmt_min(d['brady_severe'])}")
            parts.append(f"брадикардия: {_fmt_min(brad_total)}" + (f" ({'; '.join(comps)})" if comps else ""))

        lines.append("- ЧСС: " + "; ".join(parts) + ".")

        ac = base["accels"]
        if ac["count"] > 0:
            tail = []
            if ac["median_duration_s"] > 0: tail.append(f"мед. длит. {ac['median_duration_s']:.0f} с")
            if ac["max_amp_bpm"]       > 0: tail.append(f"макс +{ac['max_amp_bpm']:.0f} уд/мин")
            lines.append(f"- Акцелерации: {ac['count']}" + (f" ({'; '.join(tail)})" if tail else "") + ".")

        de = base["decels"]
        if de["count"] > 0:
            tail = []
            if de["median_duration_s"] > 0: tail.append(f"мед. длит. {de['median_duration_s']:.0f} с")
            if de["max_depth_bpm"]     > 0: tail.append(f"макс глубина −{de['max_depth_bpm']:.0f} уд/мин")
            if de["long_over_90s"]     > 0: tail.append(f">90 с: {de['long_over_90s']}")
            if de["prolonged_over_180s"] > 0: tail.append(f"≥180 с: {de['prolonged_over_180s']}")
            lines.append(f"- Децелерации: {de['count']}" + (f" ({'; '.join(tail)})" if tail else "") + ".")

        tc = r["toco"]
        

        if (tc["contractions_count"] > 0 or tc["tachysystole"] or
            tc["hypertonus"] or tc["tetanic_count"] > 0 or
            tc["mvu_per_10min_median"] > 0):
        
            head = f"- Схватки: {tc['contractions_count']} за {interval_minutes:.0f} мин"
        
            parts = []

            if tc["rate_per_10min"] > 0:
                parts.append(f"~{tc['rate_per_10min']:.1f}/10 мин")
            if tc["median_duration_s"] > 0:
                parts.append(f"мед. длит. {tc['median_duration_s']:.0f} с")
            if tc["mvu_per_10min_median"] > 0:
                lo, hi = tc["mvu_per_10min_range"]
                if lo != hi:
                    parts.append(f"активность {tc['mvu_per_10min_median']:.0f} У.Е./10 мин (диап. {lo:.0f}–{hi:.0f})")
                else:
                    parts.append(f"активность {tc['mvu_per_10min_median']:.0f} У.Е./10 мин")
            if tc["tetanic_count"] > 0:
                parts.append(f"тетанические: {tc['tetanic_count']}")
        
            flags = []
            if tc["tachysystole"]:
                flags.append("тахисистолия")
            if tc["hypertonus"]:
                flags.append("гипертонус")
            if flags:
                parts.append(", ".join(flags))
        
            if parts:
                lines.append(head + " (" + "; ".join(parts) + ").")
            else:
                lines.append(head + ".")

        if r["alerts"]:
            al = []
            for a in r["alerts"]:
                t0 = _fmt_hhmm(a.get("t_start", 0.0))
                span = f"{t0}–{_fmt_hhmm(a['t_end'])}" if a.get("t_end") is not None else t0
                al.append(f"[{a.get('severity','').upper()}] {a.get('reason','')} ({span})")
            lines.append("- Предупреждения: " + "; ".join(al))

        lines.append("")

    text = "\n".join(lines).rstrip()
    return {"intervals": intervals, "text": text}