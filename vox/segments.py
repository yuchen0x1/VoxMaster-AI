"""Time-local acoustic evidence and bounded, editable automation for spoken music."""

from __future__ import annotations

import math
import numpy as np
from scipy import ndimage, signal
from .analysis import BANDS, as_audio, check, db

# Ranges for relative changes to the user's base chain; times are seconds.
CONTROLS = {
    "body_delta_db": (-4.0, 4.0, 0.0),
    "mud_delta_db": (-4.0, 4.0, 0.0),
    "presence_delta_db": (-4.0, 4.0, 0.0),
    "air_delta_db": (-4.0, 4.0, 0.0),
    "threshold_delta_db": (-8.0, 8.0, 0.0),
    "ratio_scale": (0.5, 2.0, 1.0),
    "transient_protect": (0.0, 1.0, 0.0),
    "denoise_scale": (0.0, 1.0, 1.0),
    "space_scale": (0.0, 1.0, 1.0),
    "highpass_delta_hz": (0.0, 70.0, 0.0),
    "sibilance_delta_db": (-4.0, 0.0, 0.0),
}
MANUAL_TYPES = {
    "语音喊麦": "普通语音喊麦",
    "普通语音喊麦": "普通语音喊麦",
    "旋律喊麦": "旋律型喊麦",
    "旋律型喊麦": "旋律型喊麦",
    "普通演唱": "普通演唱",
    "高强度喊唱": "高强度喊唱",
    "Rap": "Rap",
    "混合人声": "混合人声",
    "混合音频": "人声加伴奏",
    "人声加伴奏": "人声加伴奏",
    "纯伴奏": "纯伴奏",
}


def frame_levels(x, hop, cancel):
    levels = []
    for j in range(0, len(x), hop * 250):
        check(cancel)
        block = x[j : j + hop * 250]
        power = np.mean(block * block, axis=1)
        n = len(power) // hop
        if n:
            levels.extend(db(np.sqrt(power[: n * hop].reshape(n, hop).mean(axis=1))))
        if len(power) > n * hop:
            levels.append(float(db(np.sqrt(power[n * hop :].mean()))))
    return np.asarray(levels)


def spectral_evidence(chunk, sr):
    size = min(1024, len(chunk))
    freq, spec = signal.welch(chunk, fs=sr, nperseg=size, axis=0)
    power = spec.mean(axis=1)
    energies = {k: float(power[(freq >= a) & (freq < b)].sum()) for k, (a, b) in BANDS.items()}
    total = max(sum(energies.values()), 1e-20)
    bands = {k: round(float(10 * np.log10(max(1e-12, v / total))), 2) for k, v in energies.items()}
    # Tonal concentration distinguishes a single test oscillator from a vocal-like
    # spectrum; it cannot uniquely determine whether a source is a singer.
    main = int(np.argmax(power))
    concentrated = float(power[max(0, main - 2) : main + 3].sum() / max(1e-20, power.sum()))
    return bands, concentrated


def channel_note_disagreement(x, sr):
    # Simultaneous differing strong pitches are a polyphony cue. Instrumental
    # harmonies can pass this gate too, so the type stays low confidence.
    if x.shape[1] != 2 or len(x) < 0.12 * sr:
        return False
    candidate = []
    for channel in x.T:
        win = channel[len(channel) // 2 - round(0.05 * sr) : len(channel) // 2 + round(0.05 * sr)]
        corr = signal.correlate(win, win, mode="full", method="fft")[len(win) - 1 :]
        if corr[0] < 1e-6:
            return False
        low, high = int(sr / 550), int(sr / 75)
        peaks = signal.find_peaks(corr[low:high])[0] + low
        confident = peaks[corr[peaks] > 0.68 * corr[0]]
        if not len(confident):
            return False
        candidate.append(sr / confident[0])
    interval = abs(12 * math.log2(candidate[0] / candidate[1]))
    return 1.3 < interval < 10.5


def _region_label(s):
    if not s["active"]:
        return "静音"
    if s["burst"]:
        return "强爆发音"
    if s["tail"]:
        return "尾音"
    if s["high_energy"]:
        return "高能量段"
    if s["onsets_per_s"] >= 3.8 and s["voiced_fraction"] > 0.12:
        return "快速咬字"
    if s["sustained"]:
        return "拖腔"
    if s["voiced_fraction"] > 0.65 and s["pitch_span"] >= 2 and s["stable_fraction"] > 0.55:
        return "旋律段"
    if s["voiced_fraction"] > 0.15 and s["concentration"] < 0.97:
        return "普通语音"
    return "未知"


def _source_type(s, report):
    if not s["active"]:
        return "未知类型", 0.0
    pitched = s["voiced_fraction"]
    spread = s["side_fraction"]
    if s["dual_pitch"] and spread > 0.08:
        return "混合人声", 0.50
    if spread > 0.15:
        if pitched > 0.19:
            return "人声加伴奏", 0.56
        if report.get("bpm") or report.get("acoustics", {}).get("pulse_bpm"):
            return "纯伴奏", 0.47
    if pitched < 0.12 or s["concentration"] > 0.975:
        return "未知类型", 0.30
    # A short syllable onset often exceeds the preceding consonant by 10 dB.
    # Require sustained voiced energy above the speaker's own active baseline
    # before suggesting high-intensity vocal delivery.
    if (
        s["high_energy"]
        and s["end"] - s["start"] >= 0.12
        and pitched >= 0.45
        and s["level_db"] >= report["active_db"] + 11
    ):
        return "高强度喊唱", 0.65
    if s["onsets_per_s"] >= 3.8:
        return (
            ("Rap", 0.59)
            if report.get("bpm") or report.get("acoustics", {}).get("pulse_bpm")
            else ("普通语音喊麦", 0.57)
        )
    if s["sustained"] or s["label"] == "旋律段":
        # Continuous voicing and little silence favour a singing candidate;
        # neither genre nor performer identity is inferable from F0 alone.
        singing = (
            report.get("active_fraction", 0) > 0.88
            and s["stable_fraction"] > 0.88
            and pitched > 0.88
        )
        return ("普通演唱" if singing else "旋律型喊麦"), 0.71 if spread < 0.1 else 0.54
    if pitched > 0.20 and spread < 0.16:
        return "普通语音喊麦", 0.63
    return "未知类型", 0.36


def analyze_segments(audio, sr, report, cancel=None):
    check(cancel)
    x = as_audio(audio, sr)
    hop = max(1, round(sr * 0.02))
    levels = frame_levels(x, hop, cancel)
    loud = float(np.percentile(levels, 95))
    # Explicitly distinguish very low signal from relative inter-phrase gaps.
    floor = float(np.percentile(levels, 10))
    gate = max(-105.0, min(loud - 17.0, max(loud - 32.0, floor + 7.0)))
    raw = levels > gate
    active = ndimage.median_filter(raw.astype(np.uint8), size=5, mode="nearest").astype(bool)
    active |= raw & (levels > max(float(levels.max()) - 22.0, floor + 18.0))
    typical = float(np.median(levels[active])) if active.any() else -120.0
    energy = active & (levels > typical + 7.0) & (levels >= loud - 4.0)
    energy = ndimage.median_filter(energy.astype(np.uint8), 3, mode="nearest").astype(bool)
    # Split at actual activity and burst boundaries first, then cap sustained regions
    # to keep local measurements responsive. Discard sub-60ms energy boundaries.
    cuts = {0, len(levels)}
    cuts.update((np.flatnonzero(np.diff(active)) + 1).tolist())
    transitions = np.flatnonzero(np.diff(energy.astype(int), prepend=0, append=0))
    for a, b in transitions.reshape(-1, 2):
        if b - a >= 3:
            cuts.update((int(a), int(b)))
    pitch = np.asarray(report.get("pitch_curve", []), dtype=float).reshape(-1, 2)
    tails = np.asarray(report.get("tail_times", []), dtype=float)
    for sec in tails:
        frame = round(sec * sr / hop)
        if 0 < frame < len(levels):
            cuts.add(frame)
            cuts.add(max(0, frame - 8))
    regions = []
    sorted_cuts = sorted(cuts)
    for left, right in zip(sorted_cuts, sorted_cuts[1:]):
        # Coalesce nothing across detected pauses. Break long held sounds every 0.8 s.
        n = math.ceil((right - left) / (40 if active[left:right].any() else 150))
        bounds = np.linspace(left, right, n + 1, dtype=int)
        regions.extend(zip(bounds, bounds[1:]))
    results = []
    for a, b in regions:
        check(cancel)
        start = int(a * hop)
        end = min(len(x), int(b * hop))
        if end <= start:
            continue
        chunk = x[start:end]
        seconds = (end - start) / sr
        t0, t1 = start / sr, end / sr
        bands, concentration = spectral_evidence(chunk, sr)
        mid = 0.5 * (chunk[:, 0] + chunk[:, -1])
        side = 0.5 * (chunk[:, 0] - chunk[:, -1])
        mid_e = float(np.dot(mid, mid))
        side_e = float(np.dot(side, side))
        lo, hi = np.searchsorted(pitch[:, 0], [t0, t1])
        f0 = pitch[lo:hi, 1]
        valid = f0 > 0
        hz = f0[valid]
        semitones = 12 * np.log2(hz / 440) if len(hz) else np.empty(0)
        span = float(np.ptp(np.percentile(semitones, [10, 90]))) if len(hz) else 0.0
        contiguous = valid[:-1] & valid[1:]
        stable = abs(12 * np.log2(np.maximum(f0[1:], 1) / np.maximum(f0[:-1], 1))) < 0.43
        stability = float(np.sum(stable & contiguous) / max(1, len(f0) - 1))
        voiced = float(np.mean(valid)) if len(valid) else 0.0
        window_a = max(0, a - 18)
        window_b = min(len(levels), b + 18)
        peaks = signal.find_peaks(levels[window_a:window_b], prominence=5, distance=4)[0]
        density = len(peaks) * sr / ((window_b - window_a) * hop)
        level = float(db(np.sqrt(np.mean(chunk * chunk, dtype=float))))
        peak = float(db(np.max(abs(chunk))))
        prior = float(np.median(levels[max(0, a - 5) : a])) if a else level
        is_active = bool(active[a:b].mean() >= 0.5)
        tail_index = np.searchsorted(tails, t1 - 0.025)
        is_tail = bool(tail_index < len(tails) and tails[tail_index] <= t1 + 0.025 and is_active)
        s = dict(
            start=t0,
            end=t1,
            bands_db=bands,
            level_db=round(level, 2),
            dynamic_db=round(float(np.ptp(np.percentile(levels[a:b], [10, 90]))), 2),
            peak_db=round(peak, 2),
            side_fraction=round(side_e / max(1e-20, mid_e + side_e), 4),
            voiced_fraction=round(voiced, 3),
            active=is_active,
            tail=is_tail,
            high_energy=bool(energy[a:b].mean() > 0.5),
            burst=bool(energy[a:b].any() and level - prior > 7.0),
            sustained=bool(seconds >= 0.24 and voiced > 0.75 and stability > 0.73 and span < 1.4),
            stable_fraction=round(stability, 3),
            pitch_span=round(span, 2),
            onsets_per_s=round(density, 2),
            concentration=round(concentration, 3),
            dual_pitch=False,
            plosive_candidate=bool(is_active and level - prior > 7 and bands["rumble"] > -5.0),
            sibilant_candidate=bool(is_active and bands["sibilance"] > -7.0),
        )
        if s["side_fraction"] > 0.08 and s["active"]:
            s["dual_pitch"] = channel_note_disagreement(chunk, sr)
        s["label"] = _region_label(s)
        typ, confidence = _source_type(s, report)
        s.update(
            type=typ,
            confidence=confidence,
            evidence=[
                f"区域 RMS {level:.1f} dBFS，活动门限 {gate:.1f} dBFS",
                f"有基频帧 {voiced:.0%}，相邻帧稳定比例 {stability:.0%}，起音 {density:.1f} 次/秒",
                f"侧声能量 {s['side_fraction']:.0%}，最强窄带占比 {concentration:.0%}",
            ],
            limitations=[
                "置信度表示声学规则的证据强度。",
                "音高、包络和声场无法单独区分说唱、演唱或乐器。",
            ],
        )
        results.append(s)
    return results


def recommend_automation(report):
    regions = report.get("segments", [])
    overall = report["bands_db"]
    manual = MANUAL_TYPES.get(report.get("classification"))
    automation = []
    for s in regions:
        voiced = s["voiced_fraction"]
        conf = s["confidence"]
        known_voice = manual in (
            "普通语音喊麦",
            "普通演唱",
            "旋律型喊麦",
            "高强度喊唱",
            "Rap",
        )
        trust = max(conf, 0.70 if known_voice else 0.0)
        label = s["label"]
        controls = dict(start=s["start"], end=s["end"], label=label, confidence=conf)
        for k in ("body", "mud", "presence", "air"):
            difference = overall[k] - s["bands_db"][k]
            delta = np.clip(0.25 * difference, -2.6, 1.25) * trust
            if k == "mud" and s["bands_db"][k] > -4:
                delta -= 0.7 * trust
            if k in ("presence", "air") and s["bands_db"]["sibilance"] > -8:
                delta -= 0.6 * trust
            controls[k + "_delta_db"] = round(float(delta), 2) if s["active"] else 0.0
        hot = s["high_energy"] or s["burst"]
        controls["threshold_delta_db"] = (
            round(
                float(np.clip((s["level_db"] - report["active_db"]) * 0.17, -3.0, 2.0)),
                2,
            )
            if s["active"]
            else 0.0
        )
        controls["ratio_scale"] = round(
            1.0 + 0.25 * trust if hot else (0.90 if label in ("拖腔", "快速咬字") else 1.0),
            2,
        )
        controls["transient_protect"] = 0.80 if hot else (0.65 if label == "快速咬字" else 0.33)
        controls["highpass_delta_hz"] = (
            round(38 * max(0.35, trust), 1) if s.get("plosive_candidate") else 0.0
        )
        controls["sibilance_delta_db"] = (
            round(-2.5 * max(0.4, trust), 2) if s.get("sibilant_candidate") else 0.0
        )
        # A weaker spectral subtraction mix on breath/uncertain/sibilant regions
        # helps preserve transient and high-band detail.
        controls["denoise_scale"] = (
            0.92 if not s["active"] else (0.28 if trust < 0.62 or voiced < 0.20 else 0.65)
        )
        if label in ("拖腔", "尾音", "快速咬字") or s["bands_db"]["sibilance"] > -9:
            controls["denoise_scale"] = min(controls["denoise_scale"], 0.40)
        controls["space_scale"] = (
            0.28 if trust < 0.62 else (0.55 if label == "快速咬字" else 0.65 if hot else 1.0)
        )
        melody = (
            (manual in ("普通演唱", "旋律型喊麦"))
            if manual
            else s["type"] in ("普通演唱", "旋律型喊麦")
        )
        controls["pitch_safe"] = bool(
            melody
            and trust >= 0.65
            and s["stable_fraction"] > 0.57
            and s["side_fraction"] < 0.13
            and voiced > 0.65
            and s["active"]
        )
        automation.append(controls)
    return automation


def validate_automation(regions):
    if not isinstance(regions, list) or len(regions) > 100000:
        raise ValueError("无效的分段自动化列表")
    previous = 0.0
    for region in regions:
        if not isinstance(region, dict):
            raise ValueError("分段自动化记录格式错误")
        start = region.get("start")
        end = region.get("end")
        if (
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end))
            or start < previous - 1e-8
            or start < 0
            or end <= start
        ):
            raise ValueError("自动化时间范围须为递增且无重叠的有限数值")
        previous = end
        for key, (minimum, maximum, default) in CONTROLS.items():
            value = region.get(key, default)
            if (
                not isinstance(value, (float, int))
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(f"无效的分段参数 {key}")
        if not isinstance(region.get("pitch_safe", False), bool):
            raise ValueError("无效的音高保护设置")


def control_curve(regions, key, count, hop, sr):
    default = CONTROLS[key][2]
    curve = np.full(count, default, dtype=float)
    # Convolve changes on the control grid. Distinct gaps revert to base settings.
    for region in regions:
        a = max(0, math.ceil(region["start"] * sr / hop))
        b = min(count, math.ceil(region["end"] * sr / hop))
        if b > a:
            curve[a:b] = region.get(key, default)
    sigma = max(0.5, 0.016 * sr / hop)
    return ndimage.gaussian_filter1d(curve, sigma=sigma, mode="nearest")
