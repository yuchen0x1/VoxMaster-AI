"""Observable properties of a mix. Estimates carry their units and evidence counts."""

from __future__ import annotations

import numpy as np
from scipy import signal
from .analysis import as_audio, check


def _levels_clip(audio, sr, cancel):
    """One bounded PCM pass. A near-full-scale plateau must last at least 3 samples."""
    hop = max(1, round(sr * 0.01))
    blocks = []
    near = over = rail_runs = 0
    previous = audio[:0]
    for start in range(0, len(audio), hop * 160):
        check(cancel)
        part = audio[start : start + hop * 160]
        amplitude = np.abs(part)
        near += np.count_nonzero(amplitude >= 10 ** (-0.1 / 20))
        over += np.count_nonzero(amplitude > 1)
        # Three preceding samples decide whether a run starts at a given sample.
        # Only count runs reaching their third sample inside the current part.
        buf = np.vstack((previous, part))
        eq = np.abs(np.diff(buf, axis=0)) <= 1e-7
        rail = np.abs(np.abs(buf) - 1) <= 4e-5
        pair = eq & rail[:-1] & rail[1:]
        if len(pair) >= 2:
            begins = pair[:-1] & pair[1:] & ~np.vstack((np.zeros_like(pair[:1]), pair[:-2]))
            rail_runs += np.count_nonzero(begins[max(0, len(previous) - 2) :])
        previous = buf[-3:]
        if len(part) % hop:
            part = np.pad(part, ((0, hop - len(part) % hop), (0, 0)))
        rms = np.sqrt(
            np.mean(part.reshape(-1, hop, part.shape[1]) ** 2, axis=(1, 2), dtype=np.float64)
        )
        blocks.append(20 * np.log10(np.maximum(1e-8, rms)))
    return (
        np.concatenate(blocks),
        hop / sr,
        dict(
            near_full_samples=int(near), over_full_samples=int(over), rail_plateau_runs=int(rail_runs)
        ),
    )


def _spectral_snapshot(x, sr, cancel):
    length = min(2048, len(x))
    if length < 32:
        return None, None, 0
    # Fixed window budget also bounds the cost of inspecting a long archive.
    starts = np.unique(np.linspace(0, len(x) - length, min(96, 1 + len(x) // length), dtype=int))
    taper = signal.windows.hann(length, sym=False)
    freqs = np.fft.rfftfreq(length, 1 / sr)
    power = np.zeros(len(freqs))
    for start in starts:
        check(cancel)
        data = x[start : start + length]
        window = (data - data.mean(axis=0)) * taper[:, None]
        power += (np.abs(np.fft.rfft(window, axis=0)) ** 2).sum(axis=1)
    total = power.sum()
    if total <= 1e-12:
        return None, None, len(starts)
    roll = np.searchsorted(np.cumsum(power), 0.85 * total)
    return (
        round(float(np.dot(freqs, power) / total)),
        round(float(freqs[min(roll, len(freqs) - 1)])),
        len(starts),
    )


def _attacks(levels, dt):
    # Compare current level against the quietest frame within the preceding 40 ms.
    padded = np.pad(levels, (4, 0), mode="edge")
    baseline = np.min(np.lib.stride_tricks.sliding_window_view(padded, 4)[:-1], axis=1)
    floor = max(-70, float(np.max(levels)) - 36)
    strength = np.maximum(0, levels - np.maximum(baseline, -80))
    strength[levels < floor] = 0
    peaks, _ = signal.find_peaks(np.pad(strength, 1), height=9, distance=max(1, round(0.09 / dt)))
    peaks -= 1
    return strength, peaks


def _rhythm(strength, peaks, dt):
    if len(peaks) < 6 or len(strength) * dt < 4:
        return None, None
    # Fold clipped onset strengths into the correlation so a single jump from
    # digital silence cannot dominate an otherwise unmetered track.
    envelope = np.clip(strength, 0, 24)
    envelope -= envelope.mean()
    if np.dot(envelope, envelope) < 1e-8:
        return None, None
    ac = signal.correlate(envelope, envelope, method="fft", mode="full")[len(envelope) - 1 :]
    ac /= ac[0]
    lo, hi = round(0.3 / dt), round(1 / dt)
    candidates = signal.find_peaks(ac[lo - 1 : hi + 2])[0] + lo - 1
    candidates = candidates[(candidates >= lo) & (candidates <= hi)]
    if not len(candidates):
        return None, None
    best = float(np.max(ac[candidates]))
    if best < 0.32:
        return None, None
    lag = int(candidates[ac[candidates] >= max(0.32, 0.88 * best)][0])
    return round(60 / (dt * lag), 1), round(float(ac[lag]), 3)


def _pitch_evidence(report):
    curve = np.asarray(report.get("pitch_curve", []), dtype=float)
    if curve.ndim != 2 or len(curve) < 2:
        return None, None, None, 0, 0.0, None
    times, hz = curve.T
    voiced = hz > 0
    if not voiced.any():
        return None, None, None, 0, 0.0, None
    dt = float(np.median(np.diff(times)))
    if not 0.002 < dt < 0.12:
        return None, None, None, 0, 0.0, None
    midi = np.zeros(len(hz))
    midi[voiced] = 69 + 12 * np.log2(hz[voiced] / 440)
    adjacent = voiced[1:] & voiced[:-1] & (np.diff(times) < 1.5 * dt)
    steps = abs(np.diff(midi)[adjacent]) * 100
    frame_count = max(3, round(0.24 / dt))
    sustained = np.zeros(len(hz), dtype=bool)
    if len(hz) >= frame_count:
        windows = np.lib.stride_tricks.sliding_window_view(midi, frame_count)
        v = np.lib.stride_tricks.sliding_window_view(voiced, frame_count).all(axis=1)
        steady = v & (np.ptp(windows, axis=1) <= 0.6)
        sustained = (
            signal.convolve(steady.astype(float), np.ones(frame_count), mode="full", method="direct")
            > 0
        )
    transitions = np.flatnonzero(np.diff(sustained.astype(int), prepend=0, append=0))
    lengths = np.diff(transitions.reshape(-1, 2), axis=1).ravel() * dt
    lo, hi = np.percentile(hz[voiced], [10, 90])
    detuning = None
    if len(lengths):
        stable_midi = midi[sustained]
        detuning = round(float(np.median(100 * np.abs(stable_midi - np.rint(stable_midi)))), 1)
    return (
        round(float(lo), 1),
        round(float(hi), 1),
        round(float(np.median(steps)), 1) if len(steps) else None,
        len(lengths),
        round(float(max(lengths, default=0)), 3),
        detuning,
    )


def _decay(levels, dt, report):
    durations = []
    for t in report.get("tail_times", []):
        center = round(t / dt)
        start = max(0, center - round(0.38 / dt))
        end = min(len(levels), center + round(0.5 / dt))
        if end - start < 14:
            continue
        values = levels[start:end]
        # Fit the visible decline from 3 to 23 dB below the local maximum.
        # The fitted slope includes the source envelope and any effects.
        index = int(np.argmax(values[: max(1, min(len(values), center - start + 1))]))
        after = values[index:]
        lower = np.flatnonzero(after < after[0] - 3)
        if not len(lower):
            continue
        i = int(lower[0])
        upper = np.flatnonzero(after[i:] < after[0] - 23)
        if not len(upper):
            continue
        j = i + int(upper[0])
        y = after[i:j]
        if len(y) < 10 or np.ptp(y) < 12:
            continue
        time = np.arange(len(y)) * dt
        slope, intercept = np.polyfit(time, y, 1)
        predicted = slope * time + intercept
        r2 = 1 - np.sum((y - predicted) ** 2) / max(1e-8, np.sum((y - y.mean()) ** 2))
        if slope < -8 and r2 >= 0.85:
            durations.append(-20 / slope)
    return round(float(np.median(durations)), 3) if durations else None, len(durations)


def _echo(x, sr, dt, peaks, strength, cancel):
    # Inspect at most 48 separated transients. Compare broadband shape with
    # a quieter delayed copy. Repeated percussion can pass this test as well.
    if len(peaks) < 3:
        return None, 0
    selected = sorted(peaks, key=lambda p: -strength[p])
    examined = []
    results = []
    for p in selected:
        if len(examined) >= 48:
            break
        pos = int(p * dt * sr)
        if any(abs(pos - n) < 0.55 * sr for n in examined):
            continue
        examined.append(pos)
        check(cancel)
        begin = max(0, pos - round(0.022 * sr))
        window = x[begin : begin + round(0.47 * sr)]
        if len(window) < 0.26 * sr:
            continue
        channel = np.argmax((window[: round(0.05 * sr)] ** 2).sum(axis=0))
        factor = max(1, round(sr / 9000))
        mono = signal.resample_poly(window[:, channel], 1, factor)
        # First difference attenuates vowels/bass that can correlate every period.
        data = np.diff(mono).astype(np.float64)
        rate = sr / factor
        size = round(0.045 * rate)
        pattern = data[:size]
        power = np.dot(pattern, pattern)
        if power < 1e-8:
            continue
        power_bins = abs(np.fft.rfft(pattern * np.hanning(size))) ** 2
        flat = np.exp(np.mean(np.log(np.maximum(power_bins, 1e-18)))) / max(
            1e-18, np.mean(power_bins)
        )
        if flat < 0.045:
            continue
        dots = signal.correlate(data, pattern, mode="valid", method="fft")
        sums = np.r_[0.0, np.cumsum(data**2)]
        energy = (sums[size:] - sums[:-size]).clip(min=1e-18)
        gain = dots / power
        corr = dots / np.sqrt(energy * power)
        valid = (np.arange(len(corr)) >= round(0.055 * rate)) & (gain >= 0.08) & (gain <= 0.75)
        if valid.any():
            lag = int(np.argmax(np.where(valid, corr, -1.0)))
            if corr[lag] >= 0.72:
                results.append(lag / rate)
    if len(results) < 3:
        return None, len(results)
    delays = np.array(results)
    counts = np.sum(abs(delays[:, None] - delays[None, :]) <= 0.007, axis=1)
    center = delays[np.argmax(counts)]
    support = delays[abs(delays - center) <= 0.007]
    if len(support) < 3 or len(support) < len(results) * 0.6:
        return None, len(support)
    return round(float(np.median(support)) * 1000), len(support)


def space_evidence(audio,sr,tail_times,cancel=None):
    levels,dt,_=_levels_clip(audio,sr,cancel)
    strength,peaks=_attacks(levels,dt)
    decay,count=_decay(levels,dt,{"tail_times":tail_times})
    delay,support=_echo(audio,sr,dt,peaks,strength,cancel)
    return dict(decay20_s=decay,decay_count=count,repeat_delay_ms=delay,repeat_support=support)


def extra_features(audio, sr, existing_report, cancel=None):
    """Merge the result using report.update(...). All values are plain JSON types."""
    x = as_audio(audio, sr)
    check(cancel)
    levels, dt, features = _levels_clip(x, sr, cancel)
    features["centroid_hz"], features["rolloff85_hz"], features["spectral_windows"] = (
        _spectral_snapshot(x, sr, cancel)
    )
    strength, peaks = _attacks(levels, dt)
    features["transient_count"] = len(peaks)
    features["transient_times_s"] = [round(float(dt * p), 3) for p in peaks[:24]]
    features["pulse_bpm"], features["pulse_autocorrelation"] = _rhythm(strength, peaks, dt)
    (
        features["pitch_p10_hz"],
        features["pitch_p90_hz"],
        features["adjacent_pitch_step_cents"],
        features["stable_pitch_runs"],
        features["longest_stable_s"],
        features["stable_note_offset_cents"],
    ) = _pitch_evidence(existing_report)
    features["decay20_s"], features["decay_count"] = _decay(levels, dt, existing_report)
    features["repeat_delay_ms"], features["repeat_support"] = _echo(
        x, sr, dt, peaks, strength, cancel
    )
    evidence = []
    if features["longest_stable_s"] >= 0.3:
        evidence.append("存在长时间稳定音高")
    if features["pulse_bpm"]:
        evidence.append("存在周期性强起音")
    if existing_report.get("side_fraction", 0) > 0.18:
        evidence.append("侧声道能量较强")
    features["type_evidence"] = (
        "、".join(evidence) if evidence else "缺少可重复的长音、脉冲或侧声道线索"
    )
    # A steady pitched instrument and a singer can produce the same F0.
    # Describe the observable material, leaving source identity undecided.
    category = "类型不确定"
    if features["longest_stable_s"] >= 0.30:
        category = "含稳定音高的片段"
    elif (
        features["pitch_p10_hz"] is not None
        and existing_report.get("dynamic_db", 0) > 8
        and existing_report.get("side_fraction", 0) < 0.08
        and not features["pulse_bpm"]
    ):
        category = "疑似语音型素材"
    if features["pulse_bpm"]:
        category = (
            "有规则律动的旋律素材" if features["longest_stable_s"] >= 0.30 else "有规则律动的素材"
        )
    features["acoustic_type"] = category
    check(cancel)
    return {"acoustics": features}


def report_lines(report):
    f = report.get("acoustics")
    if not f:
        return []
    rows = [
        f"电平接近满刻度的声道采样 {f['near_full_samples']} 个（≥ −0.1 dBFS），超过 0 dBFS 的有 {f['over_full_samples']} 个。",
        f"满幅连续平顶 {f['rail_plateau_runs']} 段（同一声道连续 ≥3 个近似等值采样）。",
        f"强起音 {f['transient_count']} 处（40 ms 内上升 ≥9 dB），可能来自发声、鼓击或其他瞬态。",
    ]
    if f["centroid_hz"] is not None:
        rows.append(
            f"频谱重心 {f['centroid_hz']} Hz，85% 能量低于 {f['rolloff85_hz']} Hz（{f['spectral_windows']} 个取样窗）。"
        )
    if f["pitch_p10_hz"] is not None:
        rows.append(
            f"有基频帧的 10–90 百分位为 {f['pitch_p10_hz']}–{f['pitch_p90_hz']} Hz，稳定有声音段 {f['stable_pitch_runs']} 处，最长 {f['longest_stable_s']} 秒。"
        )
    if f.get("stable_note_offset_cents") is not None:
        rows.append(
            f"稳定音段到最近十二平均律音级的偏差中位数为 {f['stable_note_offset_cents']} 音分（A4 = 440 Hz）；目标旋律需结合原谱判断。"
        )
    if f["pulse_bpm"]:
        rows.append(
            f"候选律动 {f['pulse_bpm']} BPM（起音包络自相关 {f['pulse_autocorrelation']:.2f}）。"
        )
    if f["decay20_s"] is not None:
        rows.append(
            f"尾部电平衰减 20 dB 约 {f['decay20_s']} 秒，来自 {f['decay_count']} 个可拟合片段，含人声自然收尾。"
        )
    else:
        rows.append("尾部衰减未知，缺少连续且足够长的衰减段。")
    if f["repeat_delay_ms"] is not None:
        rows.append(
            f"发现约 {f['repeat_delay_ms']} ms 的重复纹理（{f['repeat_support']} 处），也可能来自伴奏重复。"
        )
    else:
        rows.append("回声间隔未知，未发现至少三处一致的延迟纹理。")
    rows.append(
        f"{f.get('acoustic_type', '类型不确定')}。{f['type_evidence']}。单份混音的人声与伴奏占比未知。"
    )
    return rows


def compare_lines(report, reference):
    """Signed difference is always current minus reference; works with older projects."""
    rows = []

    def compare(title, a, b, unit, threshold=0):
        if a is None or b is None:
            return
        delta = a - b
        if abs(delta) >= threshold:
            rows.append(f"{title}：当前 {a:.1f}，参考 {b:.1f}，相差 {delta:+.1f} {unit}")

    compare("综合响度", report.get("lufs"), reference.get("lufs"), "LU")
    compare("活动帧动态", report.get("dynamic_db"), reference.get("dynamic_db"), "dB")
    compare("真峰值", report.get("true_peak_db"), reference.get("true_peak_db"), "dB")
    for band, title in (
        ("body", "低频厚度 80–220 Hz"),
        ("mud", "低中频 220–550 Hz"),
        ("presence", "清晰度频段 1.8–4.8 kHz"),
        ("sibilance", "齿音频段 4.8–9 kHz"),
    ):
        compare(
            title, report.get("bands_db", {}).get(band), reference.get("bands_db", {}).get(band), "dB"
        )
    if "side_fraction" in report and "side_fraction" in reference:
        compare(
            "侧声道能量占比",
            100 * report["side_fraction"],
            100 * reference["side_fraction"],
            "个百分点",
        )
    a, b = report.get("acoustics", {}), reference.get("acoustics", {})
    if a.get("decay20_s") is not None and b.get("decay20_s") is not None:
        compare("尾部下降 20 dB 所需时间", a["decay20_s"] * 1000, b["decay20_s"] * 1000, "ms")
    else:
        rows.append("尾部衰减差异未知，至少一轨缺少可拟合的收尾。")
    if a.get("repeat_delay_ms") is not None and b.get("repeat_delay_ms") is not None:
        compare("重复纹理间隔", a["repeat_delay_ms"], b["repeat_delay_ms"], "ms")
    else:
        rows.append("延迟差异未知，至少一轨缺少可靠的间隔估计。")
    rows.append("人声与伴奏的独立电平需在分轨后测量。")
    return rows
