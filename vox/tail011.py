"""Phrase-boundary evidence, pitch-preserving WSOLA and guarded wet returns."""

import itertools
from bisect import bisect_right
from copy import deepcopy
from math import isfinite
from operator import itemgetter

import numpy as np
from scipy import ndimage, signal

from .analysis import check


def slice_params(params, start, end):
    """Map persisted track-time controls onto a preview window in seconds."""
    result = deepcopy(params)
    if not isfinite(start) or not isfinite(end) or end <= start:
        raise ValueError("试听区域无效")
    if "tail_times" in result:
        result["tail_times"] = [
            t - start for t in result["tail_times"] if start <= t <= end
        ]

    def clip(rows):
        clipped = []
        for original in rows:
            a, b = max(start, original["start"]), min(end, original["end"])
            if b <= a:
                continue
            row = dict(original, start=a - start, end=b - start)
            for name in ("next_start", "next_onset"):
                if row.get(name) is not None:
                    t = row[name]
                    row[name] = t - start if start <= t < end else None
            for name in ("automation", "pitch_regions", "tail_regions"):
                if name in row:
                    row[name] = clip(row[name])
            clipped.append(row)
        return clipped

    for name in ("automation", "pitch_regions", "tail_regions"):
        if name in result:
            result[name] = clip(result[name])
    return result


def validate_edits(p):
    schemas = {
        "pitch_regions": {
            "semitones": (-5, 5),
            "speed_ms": (10, 300),
            "strength": (0, 1),
        },
        "tail_regions": {
            "stretch": (0.5, 2),
            "gain_db": (-36, 6),
            "repeats": (0, 12),
            "reverb": (0, 0.8),
            "delay": (0, 0.8),
        },
    }
    for key, limits in schemas.items():
        if key not in p:
            continue
        rows = p[key]
        if not isinstance(rows, list) or len(rows) > 2048:
            raise ValueError("选区数量或格式无效")
        normalized = []
        for row in rows:
            try:
                clean = {k: float(row[k]) for k in ("start", "end", *limits)}
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError("音频选区参数不完整") from exc
            if (
                not all(isfinite(v) for v in clean.values())
                or not 0 <= clean["start"] < clean["end"]
            ):
                raise ValueError("音频选区时间无效")
            if any(not low <= clean[k] <= high for k, (low, high) in limits.items()):
                raise ValueError("音频选区参数超过范围")
            if key == "tail_regions" and (
                clean["end"] - clean["start"] > 5 or not clean["repeats"].is_integer()
            ):
                raise ValueError("每个尾音最长 5 秒，重复次数须为整数")
            normalized.append(clean)
        normalized.sort(key=lambda r: r["start"])
        if any(a["end"] > b["start"] for a, b in itertools.pairwise(normalized)):
            raise ValueError("同一类型的编辑选区不可重叠")
        p[key] = normalized


def phrase_boundaries(levels, hop_s, duration, pitch_time=(), pitch_hz=()):
    """Identify energy islands with a locally adaptive silence floor."""
    levels = np.asarray(levels)
    if not len(levels) or levels.max() < -95:
        return []
    crest = ndimage.maximum_filter1d(
        levels, size=max(3, round(1 / hop_s)), mode="nearest"
    )
    floor = np.percentile(levels, 10)
    gate = np.maximum(
        -96,
        np.maximum(
            levels.max() - 40, np.minimum(crest - 12, np.maximum(floor + 8, crest - 28))
        ),
    )
    active = levels > gate
    boundaries = np.flatnonzero(
        np.diff(active.astype(int), prepend=0, append=0)
    ).reshape(-1, 2)
    runs = []
    for a, b in boundaries:
        if runs and (a - runs[-1][1]) * hop_s < 0.075:
            runs[-1][1] = b
        elif (b - a) * hop_s >= 0.045:
            runs.append([a, b])
    result = []
    times, hz = np.asarray(pitch_time), np.asarray(pitch_hz)
    for i, (a, b) in enumerate(runs):
        start, end = a * hop_s, min(duration, b * hop_s)
        following = runs[i + 1][0] * hop_s if i + 1 < len(runs) else None
        gap = (following if following is not None else duration) - end
        lo, hi = np.searchsorted(times, [max(start, end - 0.32), end])
        voiced = hz[lo:hi]
        voiced = voiced[voiced > 0]
        stable = len(voiced) >= 6 and np.std(12 * np.log2(voiced / voiced[0])) < 0.65
        # Decaying residual energy is evidence of a possible acoustic tail,
        # not a unique reverb estimator; keep the measured value available.
        post = levels[b : min(len(levels), b + max(1, round(0.1 / hop_s)))]
        decay = float(np.mean(post) - np.max(levels[a:b])) if len(post) else None
        candidate = end - start >= 0.15 and gap >= 0.10
        result.append(
            {
                "start": round(start, 4),
                "end": round(end, 4),
                "next_start": None if following is None else round(following, 4),
                "gap": round(max(0.0, gap), 4),
                "sustained": bool(stable),
                "candidate": bool(candidate),
                "decay_db": round(decay, 1) if decay is not None else None,
            }
        )
    return result


def audio_phrases(x, sr):
    hop = max(1, round(0.02 * sr))
    frames = len(x) // hop
    if not frames:
        return []
    # Bound intermediate memory on long takes.
    values = []
    for start in range(0, frames, 1000):
        blocks = x[start * hop : min(frames, start + 1000) * hop].reshape(
            -1, hop, x.shape[1]
        )
        values.extend(
            10 * np.log10(np.maximum(1e-12, np.mean(blocks * blocks, axis=(1, 2))))
        )
    if frames * hop < len(x):
        values.append(10 * np.log10(max(1e-12, np.mean(x[frames * hop :] ** 2))))
    return phrase_boundaries(values, hop / sr, len(x) / sr)


def guard_end(phrases, end, duration):
    index = bisect_right(phrases, end + 0.005, key=itemgetter("start"))
    if index and end < phrases[index - 1]["end"] - 0.04:
        return end
    if index < len(phrases):
        return min(duration, max(end, phrases[index]["start"] - 0.015))
    return duration


def stretch(segment, sr, count, cancel=None):
    """Time-scale a short, stereo-linked selection by waveform similarity."""
    if count == len(segment):
        return segment
    grain = min(round(sr * 0.04), len(segment) // 2, count // 2)
    if grain < 8:
        return signal.resample(segment, count, axis=0).astype("f")
    hop = grain // 2
    grain = hop * 2
    radius = max(2, round(sr * 0.009))
    window = signal.windows.hann(grain, sym=False).astype("f")
    padded = np.pad(segment, ((hop, grain), (0, 0)), mode="edge")
    mono = padded.mean(axis=1)
    result = np.zeros((count + 2 * grain, segment.shape[1]), dtype="f")
    weight = np.zeros(len(result), dtype="f")
    previous = 0
    for pos in range(0, count + hop, hop):
        check(cancel)
        expect = round(pos * len(segment) / count)
        first, last = max(0, expect - radius), min(len(padded) - grain, expect + radius)
        best = min(max(0, expect), len(padded) - grain)
        if pos and last > first:
            search = mono[first : last + hop]
            target = mono[previous + hop : previous + grain]
            score = signal.correlate(search, target, mode="valid", method="fft")
            cumulative = np.r_[0.0, np.cumsum(search.astype("d") ** 2)]
            denom = np.sqrt(np.maximum(1e-12, cumulative[hop:] - cumulative[:-hop]))
            if np.max(np.abs(score)) > 1e-12:
                best = first + int(np.argmax(score / denom))
        result[pos : pos + grain] += padded[best : best + grain] * window[:, None]
        weight[pos : pos + grain] += window
        previous = best
    return result[hop : hop + count] / np.maximum(1e-8, weight[hop : hop + count, None])


def auto_rows(p):
    manual = p.get("tail_regions", [])
    rows = list(manual)
    for t in p.get("tail_times", []):
        if t <= 0 or any(
            edit["start"] - 0.02 <= t <= edit["end"] + 0.04 for edit in manual
        ):
            continue
        rows.append(
            {
                "start": max(0, t - 0.22),
                "end": t,
                "stretch": 1.0,
                "gain_db": 0.0,
                "repeats": 12,
                "delay": p["delay"],
                "reverb": p["reverb"] if p["reverb_send"] == "Tails" else 0.0,
            }
        )
    return sorted(rows, key=lambda r: r["start"])


def guarded_space(x, sr, p, cancel, original_space):
    rows = auto_rows(p)
    dry = x.copy() if any(r["stretch"] != 1 for r in rows) else x
    phrases = audio_phrases(x, sr) if rows else []
    # Whole-track ambience remains editable independently of local phrase sends.
    result = np.zeros_like(x)
    if p["reverb_send"] == "Full" and p["reverb"]:
        result = original_space(
            x, sr, dict(p, _local_space=True, delay=0, dry=0), cancel
        )
    for row in rows:
        check(cancel)
        a, b = max(0, round(row["start"] * sr)), min(len(x), round(row["end"] * sr))
        if b <= a:
            continue
        stop = min(len(x), round(sr * guard_end(phrases, b / sr, len(x) / sr)))
        n = max(1, min(stop - a, round((b - a) * row["stretch"])))
        if n != b - a:
            scaled = stretch(x[a:b], sr, n, cancel)
            extent = max(n, b - a)
            edit = np.zeros((extent, x.shape[1]), dtype="f")
            edit[:n] = scaled
            fade = min(round(0.009 * sr), n // 3, extent // 3)
            if fade:
                ramp = np.linspace(0, 1, fade, dtype="f")[:, None]
                edit[:fade] = edit[:fade] * ramp + x[a : a + fade] * (1 - ramp)
                edit[n - fade : n] *= ramp[::-1]
                resume = a + extent
                # Avoid reintroducing the trimmed syllable at its former end
                # when it is followed by silence. Blend back only into sound.
                if resume < len(x) and np.max(np.abs(x[resume : resume + fade])) > 1e-5:
                    edit[-fade:] += x[resume - fade : resume] * ramp
            dry[a : a + extent] = edit
        if not row["reverb"] and not row["delay"]:
            continue
        delay_s = (
            60 / p["tempo_bpm"] * p["beat_fraction"]
            if p["delay_type"] == "Tempo"
            else p["delay_ms"] / 1000
        )
        step = max(1, round(sr * delay_s))
        repetitions = min(
            int(row["repeats"]), 1 if p["delay_type"] == "Slapback" else 12
        )
        total = min(
            stop - a,
            n
            + max(
                round(sr * (p["decay_s"] + p["predelay_ms"] / 1000)),
                repetitions * step + round(0.018 * sr),
            ),
        )
        if total <= 0:
            continue
        buf = np.zeros((total, x.shape[1]), dtype="f")
        buf[:n] = dry[a : a + n] * signal.windows.tukey(n, 0.25)[:, None]
        wet = np.zeros_like(buf)
        if row["reverb"]:
            wet = original_space(
                buf,
                sr,
                dict(
                    p,
                    _local_space=True,
                    reverb_send="Full",
                    dry=0,
                    reverb=row["reverb"],
                    delay=0,
                    wet_width=1,
                ),
                cancel,
            )
        for rep in range(1, repetitions + 1):
            dest = step * rep
            size = min(n, total - dest)
            if size <= 0:
                break
            gain = row["delay"] * p["feedback"] ** (rep - 1)
            if p["delay_type"] == "Ping-Pong" and x.shape[1] == 2:
                wet[dest : dest + size, (rep - 1) % 2] += buf[:size].mean(axis=1) * gain
            elif p["delay_type"] == "Stereo" and x.shape[1] == 2:
                wet[dest : dest + size, 0] += buf[:size, 0] * gain
                dest += round(0.018 * sr)
                size = max(0, min(n, total - dest))
                wet[dest : dest + size, 1] += buf[:size, 1] * gain
            else:
                wet[dest : dest + size] += buf[:size] * gain
        fade = min(total, round(sr * 0.045))
        wet[-fade:] *= np.linspace(1, 0, fade, dtype="f")[:, None]
        middle = wet.mean(axis=1, keepdims=True)
        result[a : a + total] += (middle + p["wet_width"] * (wet - middle)) * 10 ** (
            row["gain_db"] / 20
        )
    auto = p.get("automation", [])
    if auto:
        # Ramp the spatial send across region boundaries. Do not step dry gain.
        hop = max(1, round(0.01 * sr))
        ts = np.arange(0, len(x) + hop, hop) / sr
        gain = np.ones(len(ts))
        for row in auto:
            lo, hi = np.searchsorted(ts, [row["start"], row["end"]])
            gain[lo:hi] = row.get("space_scale", 1.0)
        gain = ndimage.gaussian_filter1d(gain, 1.2, mode="nearest")
        for at in range(0, len(x), sr * 8):
            check(cancel)
            idx = np.arange(at, min(at + sr * 8, len(x)))
            result[at : at + len(idx)] *= np.interp(idx / sr, ts, gain)[:, None]
    return result + dry * p["dry"]
