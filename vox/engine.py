"""Offline audio rendering and explainable, measurement-driven mix decisions."""

import math
from copy import deepcopy
import numpy as np
from scipy import ndimage, signal
from .analysis import analyze as analyze, as_audio, check, db, loudness, true_peak
from .pitch import correct_pitch
from .presets import DEFAULT, PARAMS, PRESETS, STAGES
from .segments import control_curve, recommend_automation, validate_automation, spectral_evidence


def normalize(params):
    p = {**deepcopy(DEFAULT), **deepcopy(params)}
    if "automation" in p:
        validate_automation(p["automation"])
    for name, (_, low, high, _) in PARAMS.items():
        value = float(p[name])
        if not math.isfinite(value):
            raise ValueError(f"参数 {name} 必须是有限数值")
        p[name] = max(low, min(high, value))
    stages = p["order"]
    if (
        not isinstance(stages, list)
        or len(set(stages)) != len(stages)
        or not set(stages) <= set(STAGES)
    ):
        raise ValueError("效果器顺序包含重复或未知模块")
    p["order"] = stages + [s for s in STAGES if s not in stages]
    if not isinstance(p["disabled"], list) or not set(p["disabled"]) <= set(STAGES):
        raise ValueError("无效的旁通模块")
    tails = p["tail_times"]
    if not isinstance(tails, (list, tuple)) or len(tails) > 100000:
        raise ValueError("尾音标记格式错误")
    p["tail_times"] = sorted(
        set(float(t) for t in tails if math.isfinite(float(t)) and float(t) >= 0)
    )
    if p["hum_hz"] not in (0, 50, 60) or p["beat_fraction"] not in (0.25, 0.5, 1):
        raise ValueError("无效的工频或节拍设置")
    from .tail011 import validate_edits

    validate_edits(p)
    return p


def recommend(report, style="经典喊麦", reference=None):
    p = normalize(PRESETS[style] if isinstance(style, str) else style)
    bands = report["bands_db"]
    # Preserve the taste of the chosen preset; restrict broad corrections on
    # uncertain sources, where spectral colour may belong to an instrument.
    confident = "喊麦" in report["classification"] or "旋律" in report["classification"]
    trust = 1 if confident else 0.55

    def adapt(k, change, scale=1):
        p[k] += float(np.clip(change, -3, 3)) * scale

    adapt("mud_db", (-6 - bands["mud"]) * 0.3, trust)
    adapt("body_db", (-7 - bands["body"]) * 0.18, trust)
    adapt("presence_db", (-12 - bands["presence"]) * 0.16, trust)
    adapt("air_db", (-24 - bands["air"]) * 0.08, trust)
    p["threshold_db"] = 0.35 * p["threshold_db"] + 0.65 * (report["active_db"] + 2)
    p["ratio"] += trust * float(np.clip((report["dynamic_db"] - 9) / 14, -0.5, 1.2))
    p["highpass_hz"] += trust * float(np.clip((bands["rumble"] + 16) * 1.8, -12, 25))
    p["deess"] += float(np.clip((bands["sibilance"] + 15) / 40, -0.15, 0.25))
    snr = report["active_db"] - report["noise_db"]
    scale = 0 if snr < 6 or report["noise_db"] < -75 else float(np.clip((40 - snr) / 22, 0.25, 1.7))
    p["denoise"] *= max(scale, 1.0 if report.get("hum_hz") else 0.0)
    p["tail_times"] = list(report["tail_times"])
    if report.get("hum_hz"):
        p["hum_hz"] = report["hum_hz"]
    if report.get("bpm"):
        p["tempo_bpm"] = report["bpm"]
    if p["key"] == "Auto" and report.get("key"):
        p["key"] = report["key"]
        p["scale"] = report["scale"]
    if reference:
        if reference["lufs"] <= -70:
            raise ValueError("参考音频低于响度门限")
        for band, param in (
            ("body", "body_db"),
            ("mud", "mud_db"),
            ("presence", "presence_db"),
            ("air", "air_db"),
        ):
            adapt(param, (reference["bands_db"][band] - bands[band]) * 0.35)
        adapt("ratio", (report["dynamic_db"] - reference["dynamic_db"]) * 0.08, 0.65)
        p["target_lufs"] = np.clip(reference["lufs"], -26, -12)
        p["width"] += np.clip(reference["side_fraction"] - report["side_fraction"], -0.2, 0.2)
        wet_a = report.get("late_energy_db")
        wet_b = reference.get("late_energy_db")
        if wet_a is not None and wet_b is not None:
            p["reverb"] += float(np.clip((wet_b - wet_a) * 0.003, -0.06, 0.06))
    # Imported personal styles may contain edits for another timeline.
    # Derive fresh time ranges from the current source.
    p.pop("automation", None)
    if report.get("segments"):
        p["automation"] = recommend_automation(report)
        p["tail_guard"] = True
    return normalize(p)


def eq_sos(sr, p):
    filters = list(signal.butter(2, p["highpass_hz"], "highpass", fs=sr, output="sos"))
    for band in ("body", "mud", "presence", "air"):
        hz = min(sr * 0.46, p[band + "_hz"])
        w = 2 * np.pi * hz / sr
        c = np.cos(w)
        amplitude = 10 ** (p[band + "_db"] / 40)
        if band == "air":
            a = amplitude
            m = np.sin(w) * np.sqrt(2 * a)
            b0 = a * ((a + 1) + (a - 1) * c + m)
            b1 = -2 * a * ((a - 1) + (a + 1) * c)
            b2 = a * ((a + 1) + (a - 1) * c - m)
            a0 = (a + 1) - (a - 1) * c + m
            a1 = 2 * ((a - 1) - (a + 1) * c)
            a2 = (a + 1) - (a - 1) * c - m
        else:
            alpha = np.sin(w) / (2 * p["eq_q"])
            b0, b1, b2 = 1 + alpha * amplitude, -2 * c, 1 - alpha * amplitude
            a0, a1, a2 = 1 + alpha / amplitude, -2 * c, 1 - alpha / amplitude
        filters.append(np.array([b0, b1, b2, a0, a1, a2]) / a0)
    return np.array(filters)


def filter_audio(x, sos, cancel):
    y = np.empty_like(x)
    zi = np.zeros((len(sos), 2, x.shape[1]))
    for i in range(0, len(x), 131072):
        check(cancel)
        y[i : i + 131072], zi = signal.sosfilt(sos, x[i : i + 131072], axis=0, zi=zi)
    return y


def block_meter(x, hop, peak=False):
    aligned = len(x) // hop * hop
    chunks = []
    if aligned:
        blocks = x[:aligned].reshape(-1, hop, x.shape[1])
        if peak:
            chunks = np.max(np.abs(blocks), axis=(1, 2))
        else:
            chunks = np.sqrt(np.mean(blocks * blocks, axis=(1, 2)))
    if aligned < len(x):
        tail = x[aligned:]
        value = np.max(np.abs(tail)) if peak else np.sqrt(np.mean(tail * tail))
        chunks = np.append(chunks, value)
    return np.asarray(chunks)


def envelope(values, hop, sr, attack, release, cancel):
    a = np.exp(-1000 * hop / (sr * attack))
    r = np.exp(-1000 * hop / (sr * release))
    out = np.empty_like(values)
    state = 0.0
    for i, value in enumerate(values):
        if i % 8192 == 0:
            check(cancel)
        coeff = a if value > state else r
        state = value + (state - value) * coeff
        out[i] = state
    return out


def apply_envelope(x, levels, hop, offset=0):
    # Interpolate controls with bounded working memory for long tracks.
    y = np.empty_like(x)
    positions = np.arange(len(levels)) * hop + offset
    for i in range(0, len(x), 131072):
        idx = np.arange(i, min(len(x), i + 131072))
        y[i : i + len(idx)] = x[i : i + len(idx)] * np.interp(idx, positions, levels)[:, None]
    return y


def compression_curve(x, sr, p, cancel=None):
    hop = max(1, round(sr * 0.002))
    levels = db(block_meter(x, hop))
    over = levels - p["threshold_db"]
    regions = p.get("automation")
    ratio = p["ratio"]
    if regions:
        over -= control_curve(regions, "threshold_delta_db", len(levels), hop, sr)
        ratio = np.clip(ratio * control_curve(regions, "ratio_scale", len(levels), hop, sr), 1, 12)
    knee = p["knee_db"]
    change = np.maximum(0, over)
    if knee:
        middle = np.abs(over) < knee / 2
        change[middle] = (over[middle] + knee / 2) ** 2 / (2 * knee)
    target = change * (1 - 1 / ratio)
    if regions:
        # A level jump above the recent local envelope temporarily reduces the
        # requested attenuation; the steady note returns to normal compression.
        history = max(1, round(0.025 * sr / hop))
        average = max(1, round(0.012 * sr / hop))
        power = np.pad(10 ** (levels / 10), (average - 1, 0), mode="edge")
        local = 10 * np.log10(
            np.maximum(np.convolve(power, np.ones(average) / average, mode="valid"), 1e-12)
        )
        minimum = ndimage.minimum_filter1d(
            local, size=2 * history + 1, origin=history, mode="nearest"
        )
        onset = np.clip((local - minimum - 4) / 12, 0, 1)
        protection = control_curve(regions, "transient_protect", len(levels), hop, sr)
        target *= 1.0 - 0.82 * onset * protection
    gr = envelope(target, hop, sr, p["attack_ms"], p["release_ms"], cancel)
    return hop, gr


def region_eq(x, sr, p, cancel):
    base = filter_audio(x, eq_sos(sr, p), cancel)
    regions = p.get("automation")
    if not regions:
        return base
    y = base.copy()
    ramp = max(1, round(0.020 * sr))
    for row in regions:
        check(cancel)
        local = dict(p)
        local["highpass_hz"] = min(450.0, p["highpass_hz"] + row.get("highpass_delta_hz", 0.0))
        for key in ("body", "mud", "presence", "air"):
            gain = p[key + "_db"]
            # Keep user boosts, limit automatic additions to 4.5 dB in total.
            local[key + "_db"] = np.clip(gain + row.get(key + "_delta_db", 0.0), -9, max(gain, 4.5))
        hiss_gain = row.get("sibilance_delta_db", 0.0)
        if (
            local["highpass_hz"] == p["highpass_hz"]
            and not hiss_gain
            and all(local[k + "_db"] == p[k + "_db"] for k in ("body", "mud", "presence", "air"))
        ):
            continue
        start = round(row["start"] * sr)
        end = round(row["end"] * sr)
        a = max(0, start - ramp)
        b = min(len(x), end + ramp)
        if b <= a:
            continue
        warm = max(0, a - round(0.35 * sr))
        filters = eq_sos(sr, local)
        if hiss_gain and sr >= 12000:
            # Local Q=1 bell around the sibilance band. The measured spectrum
            # enables it only in affected regions, independent of the air shelf.
            w = 2 * np.pi * min(6500.0, sr * 0.41) / sr
            alpha = np.sin(w) / 2
            amp = 10 ** (hiss_gain / 40)
            bell = np.array(
                [
                    1 + alpha * amp,
                    -2 * np.cos(w),
                    1 - alpha * amp,
                    1 + alpha / amp,
                    -2 * np.cos(w),
                    1 - alpha / amp,
                ]
            ) / (1 + alpha / amp)
            filters = np.vstack((filters, bell))
        variant = filter_audio(x[warm:b], filters, cancel)[a - warm :]
        t = np.arange(a, b)

        # Each edge is a half cosine. Adjacent regions have complementary weights;
        # subtracting the exit ramp also handles regions shorter than the ramp.
        def edge(boundary, positions=t):
            phase = np.clip((positions - boundary + ramp) / (2 * ramp), 0, 1)
            return 0.5 - 0.5 * np.cos(np.pi * phase)

        weight = (edge(start) if start > 0 else 1.0) - (edge(end) if end < len(x) else 0.0)
        y[a:b] += (variant - base[a:b]) * np.asarray(weight).reshape(-1, 1)
    return y


def quiet_sample(x, sr):
    length = min(len(x), max(1, round(0.035 * sr)))
    offsets = np.linspace(0, len(x) - length, min(256, 1 + len(x) // length), dtype=int)
    power = np.array([np.mean(x[i : i + length] ** 2, dtype=np.float64) for i in offsets])
    idx = np.argsort(power)[: max(1, len(power) // 10)]
    return length, offsets[idx], float(db(np.sqrt(np.mean(power[idx]))))


def audit_compression(curve, hop, sr):
    stride = max(1, math.ceil(len(curve) / 2000))
    sampled = np.maximum.reduceat(curve, np.arange(0, len(curve), stride))
    return dict(
        max_gr_db=round(float(np.max(curve)), 3),
        p95_gr_db=round(float(np.percentile(curve, 95)), 3),
        over_6db_fraction=round(float(np.mean(curve > 6)), 4),
        window_s=stride * hop / sr,
        curve=[
            [round(i * stride * hop / sr, 4), round(float(v), 3)] for i, v in enumerate(sampled)
        ],
    )


def audit_spectrum(x, sr):
    # Apply identical Welch snapshots to the pre/post-EQ streams. Short files
    # use every sample; long recordings use 64 time-distributed windows.
    size = 2048
    if len(x) > 64 * size:
        starts = np.linspace(0, len(x) - size, 64, dtype=int)
        x = np.concatenate([x[i : i + size] for i in starts])
    return spectral_evidence(x, sr)[0]


def denoise_audio(x, sr, p, cancel):
    strength = p["denoise"]
    if p["hum_hz"] and strength > 0:
        filters = []
        for multiplier in (1, 2):
            b, a = signal.iirnotch(p["hum_hz"] * multiplier, 32, fs=sr)
            filters.append(np.r_[b, a])
        cut = filter_audio(x, np.array(filters), cancel)
        mix = min(1.0, strength * 1.8)
        x = x * (1 - mix) + mix * cut
    if strength <= 0 or len(x) < 1024:
        return x
    size = 1024
    hop = size // 2
    # Estimate one stationary noise spectrum from the quietest real frames.
    # For a continuously voiced input a reliable noise-only interval is absent.
    starts = np.linspace(0, len(x) - size, min(700, max(1, len(x) // hop)), dtype=int)
    frames = x[starts[:, None] + np.arange(size)]
    levels = np.sqrt(np.mean(frames * frames, axis=(1, 2)))
    quiet = np.percentile(levels, 12)
    if quiet < 1e-6 or quiet > 0.65 * np.percentile(levels, 95):
        return x
    window = np.sqrt(signal.windows.hann(size, sym=False)).astype(np.float32)
    noise_frames = frames[levels <= quiet]
    noise = np.median(
        np.abs(np.fft.rfft(noise_frames * window[None, :, None], axis=1)) ** 2, axis=(0, 2)
    )
    padded = np.pad(x, ((hop, size), (0, 0)))
    y = np.zeros_like(padded)
    for base in range(0, len(x) + hop, hop * 128):
        check(cancel)
        offsets = np.arange(base, min(len(x) + hop, base + hop * 128), hop)
        idx = offsets[:, None] + np.arange(size)
        spec = np.fft.rfft(padded[idx] * window[None, :, None], axis=1)
        power = np.mean(np.abs(spec) ** 2, axis=2)
        mask = np.clip(
            1 - strength * 1.6 * noise[None, :] / np.maximum(power, 1e-11), 1 - strength * 0.78, 1
        )
        mask = ndimage.gaussian_filter(mask, (1.0, 1.0), mode="nearest")
        blocks = np.fft.irfft(spec * mask[:, :, None], n=size, axis=1) * window[None, :, None]
        for start, block in zip(offsets, blocks):
            y[start : start + size] += block
    return y[hop : hop + len(x)]


def deess_audio(x, sr, p, cancel):
    if not p["deess"] or sr < 12000:
        return x
    sos = signal.butter(
        2, [min(4900, sr * 0.32), min(11000, sr * 0.47)], "bandpass", fs=sr, output="sos"
    )
    high = filter_audio(x, sos, cancel)
    hop = max(1, round(sr * 0.004))
    high_rms = block_meter(high, hop)
    relative = high_rms / np.maximum(1e-6, block_meter(x, hop))
    reduction = (
        np.clip((relative - 0.17) * 1.5, 0, 1)
        * np.clip((db(high_rms) + 55) / 16, 0, 1)
        * p["deess"]
        * 0.85
    )
    return x - apply_envelope(high, envelope(reduction, hop, sr, 4, 50, cancel), hop)


def saturate(x, sr, p, cancel):
    d = p["drive"]
    if not d:
        return x
    kind = p["saturation_type"]
    if kind in ("Radio", "Megaphone"):
        band = [240, min(3400, sr * 0.45)] if kind == "Radio" else [500, min(2500, sr * 0.45)]
        shaped = filter_audio(x, signal.butter(3, band, "bandpass", fs=sr, output="sos"), cancel)
        return (1 - d) * x + d * np.tanh(shaped * (1 + d * 2)) / (1 + d * 0.75)
    if kind == "Exciter":
        high = filter_audio(
            x, signal.butter(2, min(3000, sr * 0.4), "highpass", fs=sr, output="sos"), cancel
        )
        return x + d * 0.18 * (np.tanh(high * 3) - high)
    if kind == "Tube":
        driven = (1 + 3 * d) * x + 0.18
        wet = (np.tanh(driven) - np.tanh(0.18)) / (1 + 1.5 * d)
    elif kind == "Soft Clip":
        driven = x * (1 + d)
        wet = driven / (1 + np.abs(driven)) / (1 + 0.2 * d)
    else:
        wet = np.tanh(x * (1 + 2 * d)) / (1 + d * 0.85)
    return x * (1 - d) + wet * d


def stereo(x, width):
    if x.shape[1] == 1 or width == 1:
        return x
    mid = x.mean(axis=1)
    side = 0.5 * (x[:, 0] - x[:, 1]) * width
    return np.column_stack((mid + side, mid - side))


def space_audio(x, sr, p, cancel):
    if not p.get("_local_space") and (
        p.get("tail_regions") or p.get("automation") or p.get("tail_guard")
    ):
        from .tail011 import guarded_space

        return guarded_space(x, sr, p, cancel, space_audio)
    if not p["reverb"] and not p["delay"] and p["dry"] == 1:
        return x
    wet = np.zeros_like(x)
    if p["reverb"]:
        send = x
        if p.get("reverb_send") == "Tails":
            mask = np.zeros(len(x), dtype=np.float32)
            for t in p["tail_times"]:
                end = min(len(x), round(t * sr))
                start = max(0, end - round(0.24 * sr))
                if end > start:
                    mask[start:end] = np.maximum(
                        mask[start:end], signal.windows.tukey(end - start, 0.5)
                    )
            send = x * mask[:, None]
        room = {
            "Room": 0.70,
            "Hall": 1.3,
            "Plate": 0.85,
            "Spring": 0.58,
            "Studio": 0.82,
            "Large Space": 1.65,
            "Dark Hall": 1.28,
            "Bright Hall": 1.42,
        }.get(p["room_type"], 1)
        size = p["size"] * room
        irlen = max(128, int(sr * p["decay_s"]))
        for ch in range(x.shape[1]):
            check(cancel)
            # Parallel feedback combs diffuse into two short all-pass sections.
            response = np.zeros(irlen)
            for ms in (19.7, 23.9, 29.3, 31.7, 37.9, 41.1, 43.7, 47.3):
                spacing = max(1, round((ms + ch * 1.7) * size * sr / 1000))
                positions = np.arange(spacing, irlen, spacing)
                response[positions] += np.exp(-6.908 * positions / (sr * p["decay_s"]))
            for ms in (4.7, 1.9):
                lag = max(1, round(ms * size * sr / 1000))
                # Truncated all-pass impulse with geometric tail.
                taps = np.zeros(lag * 17 + 1)
                taps[0] = -0.57
                taps[lag::lag] = (1 - 0.57**2) * 0.57 ** np.arange(17)
                response = signal.fftconvolve(response, taps)[:irlen]
            response /= max(np.linalg.norm(response), 1e-8)
            hi = min(
                sr * 0.45,
                p["wet_high_hz"]
                * (1 - 0.55 * p["damping"])
                * ({"Dark Hall": 0.65, "Bright Hall": 1.16}.get(p["room_type"], 1)),
            )
            hi = max(p["wet_low_hz"] + 50, hi)
            sos = signal.butter(2, [p["wet_low_hz"], hi], "bandpass", fs=sr, output="sos")
            response = signal.sosfilt(sos, response).astype(np.float32)
            offset = round(sr * p["predelay_ms"] / 1000)
            # Accumulate overlap-add blocks to keep allocations bounded.
            for start in range(0, len(x) - offset, sr * 8):
                check(cancel)
                y = signal.oaconvolve(send[start : start + sr * 8, ch], response)
                end = min(len(x), start + offset + len(y))
                wet[start + offset : end, ch] += y[: end - start - offset] * p["reverb"]
    if p["delay"] and p["tail_times"]:
        delay_ms = (
            60000 / p["tempo_bpm"] * float(p["beat_fraction"])
            if p["delay_type"] == "Tempo"
            else p["delay_ms"]
        )
        step = max(1, round(delay_ms * sr / 1000))
        for t in p["tail_times"]:
            check(cancel)
            end = min(len(x), round(t * sr))
            start = max(0, end - round(sr * 0.22))
            if end <= start:
                continue
            window = signal.windows.tukey(end - start, 0.4).astype(np.float32)
            segment = x[start:end] * window[:, None]
            gain = p["delay"]
            for rep in range(1, 23):
                at = start + step * rep
                if at >= len(x) or gain < 0.004:
                    break
                n = min(len(segment), len(x) - at)
                if p["delay_type"] == "Ping-Pong" and x.shape[1] == 2:
                    ch = (rep - 1) % 2
                    wet[at : at + n, ch] += segment[:n].mean(axis=1) * gain
                elif p["delay_type"] == "Stereo" and x.shape[1] == 2:
                    wet[at : at + n, 0] += segment[:n, 0] * gain
                    right = at + int(0.018 * sr)
                    nr = max(0, min(len(segment), len(x) - right))
                    wet[right : right + nr, 1] += segment[:nr, 1] * gain
                else:
                    wet[at : at + n] += segment[:n] * gain
                if p["delay_type"] == "Slapback":
                    break
                gain *= p["feedback"]
    return x * p["dry"] + stereo(wet, p["wet_width"])


def master(x, sr, p, cancel):
    level = loudness(x, sr, cancel)
    if level <= -70:
        return protect_peak(x, sr, p["ceiling_db"], cancel)
    peak = max(1e-8, float(np.max(np.abs(x))))
    # Keep the normalization within the limiter's 4 dB working budget.
    gain_db = min(p["target_lufs"] - level, 36.0, p["ceiling_db"] - float(db(peak)) + 4)
    x = x * 10 ** (gain_db / 20)
    hop = max(1, round(sr * 0.002))
    peaks = block_meter(x, hop, peak=True)
    required = np.maximum(0, db(peaks) - p["ceiling_db"])
    anticipatory = ndimage.maximum_filter1d(required, size=5, mode="nearest")
    release = np.exp(-hop / (sr * 0.07))
    last = 0.0
    for i, value in enumerate(anticipatory):
        if i % 8192 == 0:
            check(cancel)
        last = max(value, last * release)
        anticipatory[i] = last
    x = apply_envelope(x, 10 ** (-anticipatory / 20), hop, hop / 2)
    return protect_peak(x, sr, p["ceiling_db"], cancel)


def protect_peak(x, sr, ceiling_db, cancel):
    ceiling = 10 ** (ceiling_db / 20)
    actual = true_peak(x, sr, cancel)
    if actual > ceiling:
        x = x * (ceiling / actual)
    return x


def process(audio, sr, params, cancel=None, progress=None, *, audit=None, tap=None):
    check(cancel)
    p = normalize(params)
    x = as_audio(audio, sr)
    if not np.isfinite(x).all():
        raise ValueError("录音包含非有限采样值")
    x = x.copy()
    enabled = [stage for stage in p["order"] if stage not in p["disabled"]]
    log = {"stages": [], "changed_stages": [], "warnings": []} if audit is not None else None
    for i, stage in enumerate(enabled):
        check(cancel)
        if progress:
            progress(i / len(enabled), STAGES[stage])
        before = x if log is not None or tap is not None else None
        if stage == "denoise":
            dry = x
            x = denoise_audio(x, sr, p, cancel)
            if p.get("automation") and x is not dry:
                hop = max(1, round(sr * 0.008))
                mix = control_curve(
                    p["automation"], "denoise_scale", math.ceil(len(x) / hop), hop, sr
                )
                x = dry + apply_envelope(x - dry, mix, hop)
            if log is not None:
                length, offsets, quiet_before = quiet_sample(dry, sr)
                powers = [np.mean(x[j : j + length] ** 2, dtype=float) for j in offsets]
                quiet_after = float(db(np.sqrt(np.mean(powers))))
                log["denoise"] = dict(
                    quiet_before_db=quiet_before,
                    quiet_after_db=quiet_after,
                    quiet_delta_db=quiet_after - quiet_before,
                    windows=len(offsets),
                    strength=p["denoise"],
                )
            del dry
        elif stage == "pitch":
            x = correct_pitch(x, sr, p, cancel)
        elif stage == "eq":
            x = region_eq(x, sr, p, cancel)
            if log is not None:
                log["eq"] = dict(
                    before_bands_db=audit_spectrum(before, sr), after_bands_db=audit_spectrum(x, sr)
                )
        elif stage == "compress":
            hop, curve = compression_curve(x, sr, p, cancel)
            x = apply_envelope(x, 10 ** ((p["makeup_db"] - curve) / 20), hop)
            if log is not None:
                info = log["compression"] = audit_compression(curve, hop, sr)
                if info["p95_gr_db"] > 8 or info["over_6db_fraction"] > 0.3:
                    log["warnings"].append(
                        f"压缩器第 95 百分位增益衰减 {info['p95_gr_db']:.1f} dB，请等响试听爆发音和抽吸。"
                    )
        elif stage == "deess":
            x = deess_audio(x, sr, p, cancel)
        elif stage == "saturate":
            x = saturate(x, sr, p, cancel)
        elif stage == "space":
            x = space_audio(x, sr, p, cancel)
        elif stage == "stereo":
            x = stereo(x, p["width"])
        elif stage == "master":
            x = master(x, sr, p, cancel)
        if tap is not None:
            tap(stage, before, x)
        if log is not None:
            log["stages"].append(stage)
            if x is not before and not np.array_equal(x, before):
                log["changed_stages"].append(stage)
    if "master" in enabled and enabled[-1] != "master":
        x = protect_peak(x, sr, p["ceiling_db"], cancel)
    check(cancel)
    if not np.isfinite(x).all():
        raise ValueError("输出含有无效采样，已停止渲染")
    if progress:
        progress(1.0, "渲染完成")
    if log is not None:
        for key in ("denoise", "eq", "compression"):
            audit.pop(key, None)
        audit.update(log)
    return np.asarray(x, dtype=np.float32)
