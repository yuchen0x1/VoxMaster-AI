"""Meters and render checks shared by the workstation and listening trials."""

from math import log10

import numpy as np
from scipy.signal import sosfilt

from .analysis import check, k_weight


def quality_metrics(audio, sr, report, cancel=None):
    """Measure stereo correlation and ungated three-second K-weighted loudness.

    Analyse float64 blocks with continuous IIR state. Short-term values are
    sampled once a second; material shorter than one complete window is unknown.
    """
    filters = k_weight(sr)
    state = np.zeros((len(filters), 2, audio.shape[1]))
    energy = []
    channel_sum = np.zeros(audio.shape[1])
    products = np.zeros((audio.shape[1], audio.shape[1]))
    segments = report.get("segments", [])
    bounds = [(round(part["start"] * sr), round(part["end"] * sr)) for part in segments]
    sums = np.zeros(len(segments))
    counts = np.zeros(len(segments), dtype=int)
    first = 0
    for start in range(0, len(audio), sr):
        check(cancel)
        block = audio[start : start + sr].astype(np.float64, copy=False)
        weighted, state = sosfilt(filters, block, axis=0, zi=state)
        channel_sum += block.sum(axis=0)
        products += block.T @ block
        squares = np.square(weighted).sum(axis=1)
        if len(block) == sr:
            energy.append(float(squares.mean()))
        while first < len(bounds) and bounds[first][1] <= start:
            first += 1
        for index in range(first, len(bounds)):
            lo, hi = bounds[index]
            if lo >= start + len(block):
                break
            local = squares[max(0, lo - start) : min(hi - start, len(block))]
            sums[index] += local.sum()
            counts[index] += len(local)
    for part, power, count in zip(segments, sums, counts):
        part["k_level"] = max(-120.0, -0.691 + 10 * log10(max(1.0e-20, power / max(1, count))))
    curve = []
    for end in range(3, len(energy) + 1):
        power = sum(energy[end - 3 : end]) / 3
        curve.append([end, max(-120.0, -0.691 + 10 * log10(max(1.0e-20, power)))])
    covariance = products - np.outer(channel_sum, channel_sum) / len(audio)
    corr = None
    if audio.shape[1] == 2:
        norm = np.sqrt(max(0.0, covariance[0, 0]) * max(0.0, covariance[1, 1]))
        if norm > 1.0e-16:
            corr = float(np.clip(covariance[0, 1] / norm, -1, 1))
    return {
        "short_term_lufs": curve,
        "short_term_max_lufs": max((v for _, v in curve), default=None),
        "crest_db": float(report["peak_db"] - report["rms_db"]),
        "stereo_correlation": corr,
    }


def validate_buffer(audio, frames, channels, cancel=None):
    if audio.shape != (frames, channels) or not frames:
        raise ValueError(
            f"渲染长度或声道异常，应为 {frames} 帧 × {channels} 声道，实得 {audio.shape}。"
        )
    for start in range(0, frames, 262144):
        check(cancel)
        if not np.isfinite(audio[start : start + 262144]).all():
            raise ValueError("渲染出现非有限采样，已中止提交。")


def assess(before, after, target, audit, aligned=True):
    """Flag reviewable evidence. Intentionally avoid a composite quality score."""
    warnings = list(audit.get("warnings", []))
    if after["clipped_samples"]:
        warnings.append(
            f"输出仍有 {after['clipped_samples']} 个接近满量程的声道采样，请降低母线增益。"
        )
    if before["lufs"] > -60 and after["lufs"] <= -70:
        warnings.append("输入含有效信号，输出低于响度门限；请检查静音、包络与效果器。")
    if target is not None and abs(after["lufs"] - target) > 3:
        warnings.append(f"成品偏离响度目标 {after['lufs'] - target:+.1f} LU，请结合真峰值余量试听。")
    # Compare local envelopes after removing the overall level offset. Intentional
    # edits can move material on the timeline, so only compare aligned passes.
    if aligned:
        wet = dict(after["short_term_lufs"])
        changes = [
            (t, wet[t] - level)
            for t, level in before["short_term_lufs"]
            if t in wet and level > -55 and wet[t] > -70
        ]
        if len(changes) >= 3:
            typical = float(np.median([change for _, change in changes]))
            t, change = max(changes, key=lambda item: abs(item[1] - typical))
            if abs(change - typical) > 8:
                warnings.append(
                    f"{t - 3}–{t} 秒短时响度变化比全曲典型变化偏离 {change - typical:+.1f} LU，建议检查该段。"
                )
    return list(dict.fromkeys(warnings))
