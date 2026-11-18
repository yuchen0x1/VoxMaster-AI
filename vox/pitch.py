"""Pitch-synchronous overlap-add for confident monophonic voiced intervals."""

import numpy as np
from scipy import ndimage

from .analysis import NOTES, check, pitch_track


def correct_pitch(x, sr, p, cancel):
    edits = p.get("pitch_regions", [])
    if p["pitch_strength"] <= 0 and not p["semitones"] and not edits:
        return x
    times, hz, periodicity = pitch_track(x, sr, cancel, return_confidence=True)
    if not len(hz):
        return x
    mask = (hz > 0) & (periodicity >= 0.79)
    # A register change must start a new pitch-mark sequence. Bridging these
    # boundaries can duplicate a consonant or flatten an octave transition.
    nonzero = np.maximum(1.0, hz)
    leap = np.abs(12 * np.diff(np.log2(nonzero))) > 4.5
    leap &= mask[1:] & mask[:-1]
    mask[1:] &= ~leap
    mask[:-1] &= ~leap
    automation = p.get("automation") or []
    allowed = (
        np.zeros(len(times), dtype=bool)
        if automation
        else np.ones(len(times), dtype=bool)
    )
    for row in automation:
        left, right = np.searchsorted(times, [row["start"], row["end"]])
        allowed[left:right] = row.get("pitch_safe", False)
    adjust = np.full(len(times), p["semitones"], dtype="d")
    speed = np.full(len(times), p["pitch_speed_ms"], dtype="d")
    strength = np.full(len(times), p["pitch_strength"], dtype="d")
    for row in edits:
        left, right = np.searchsorted(times, [row["start"], row["end"]])
        allowed[left:right] = True
        adjust[left:right] = row["semitones"]
        speed[left:right] = row["speed_ms"]
        strength[left:right] = row["strength"]
    mask &= allowed & ((strength > 0) | (np.abs(adjust) > 0))
    edges = np.flatnonzero(np.diff(mask.astype(int), prepend=0, append=0))
    out = x.copy()
    for begin, end in edges.reshape(-1, 2):
        check(cancel)
        if end - begin < 5:
            continue
        timespan = times[begin:end]
        f0 = ndimage.median_filter(hz[begin:end], size=3, mode="nearest")
        midi = 69 + 12 * np.log2(f0 / 440.0)
        targets = np.arange(0, 128)
        if p["key"] in NOTES and p["scale"] in ("Major", "Minor"):
            degrees = (
                (0, 2, 4, 5, 7, 9, 11)
                if p["scale"] == "Major"
                else (0, 2, 3, 5, 7, 8, 10)
            )
            targets = targets[np.isin((targets - NOTES.index(p["key"])) % 12, degrees)]
        nearest = targets[np.argmin(np.abs(midi[:, None] - targets), axis=1)]
        delta = (
            np.clip(nearest - midi, -1.25, 1.25) * strength[begin:end]
            + adjust[begin:end]
        )
        smooth = np.empty_like(delta)
        smooth[0] = 0.0
        for j in range(1, len(delta)):
            alpha = -np.expm1(
                -1000 * (timespan[j] - timespan[j - 1]) / speed[begin + j]
            )
            smooth[j] = smooth[j - 1] + (delta[j] - smooth[j - 1]) * alpha
        if np.max(np.abs(smooth)) < 0.015:
            continue
        start = max(0, round(timespan[0] * sr))
        stop = min(len(x), round(timespan[-1] * sr) + 1)
        seg = x[start:stop]
        mono = seg.mean(axis=1)
        timeline = timespan * sr - start
        period = sr / f0
        first = max(1, int(period[0]))
        if len(seg) < first * 5:
            continue
        # Track positive peaks inside one pitch-cycle neighbourhood. Choosing whole
        # grains from the same time region retains the local spectral envelope.
        marks = [int(np.argmax(mono[:first]))]
        while True:
            per = np.interp(marks[-1], timeline, period)
            left = int(marks[-1] + per * 0.78)
            right = int(marks[-1] + per * 1.22)
            if right >= len(seg) or left >= right:
                break
            marks.append(left + int(np.argmax(mono[left:right])))
        marks = np.asarray(marks)
        if len(marks) < 4:
            continue
        recon = np.zeros_like(seg)
        weight = np.zeros(len(seg), np.float32)
        pos = float(marks[1])
        i = 1
        while pos < marks[-2]:
            if i % 512 == 0:
                check(cancel)
            dest = round(pos)
            while i + 1 < len(marks) - 1 and abs(marks[i + 1] - pos) < abs(
                marks[i] - pos
            ):
                i += 1
            src = marks[i]
            radius = max(2, round(np.interp(src, timeline, period)))
            offsets = np.arange(
                max(-radius, -src, -dest),
                min(radius + 1, len(seg) - src, len(seg) - dest),
            )
            window = 0.5 + 0.5 * np.cos(np.pi * offsets / radius)
            recon[dest + offsets] += seg[src + offsets] * window[:, None]
            weight[dest + offsets] += window
            pos += np.interp(pos, timeline, period) * 2 ** (
                -np.interp(pos, timeline, smooth) / 12
            )
        valid = weight > 0.07
        recon[valid] /= weight[valid, None]
        indices = np.arange(len(seg))
        fade = (
            np.clip(
                np.minimum(indices - marks[1], marks[-2] - indices) / (sr * 0.015), 0, 1
            )
            * valid
        )
        out[start:stop] += (recon - seg) * fade[:, None]
    return out
