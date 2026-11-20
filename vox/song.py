"""Measured song DSP; the caller owns engine processing and Studio Session mixing.

Order: engine.process(vocal, vocal_params(...)), process_stems, Session.render,
then master_mix. Stems remain floating point and are never clipped or mixed here.
"""

import math
from collections.abc import Mapping
from numbers import Real

import numpy as np

from . import engine
from .analysis import as_audio, check, loudness, true_peak
from .presets import PRESETS

TARGETS = {
    "natural": "自然还原",
    "forward": "人声靠前",
    "impact": "力量冲击",
    "clear": "清晰通透",
    "full": "厚实饱满",
    "custom": "自定义",
}
MASTERING = {
    "conservative": "保守母带",
    "standard": "标准母带",
    "strong": "增强母带",
    "custom": "自定义",
}

# Strict editing limits, not silent clamping of user-supplied plans.
_LIMITS = {
    "vocal_gain_db": (-24.0, 12.0, 0.0),
    "instrumental_gain_db": (-24.0, 12.0, 0.0),
    "instrumental_low_db": (-6.0, 6.0, 0.0),
    "instrumental_mid_db": (-6.0, 6.0, 0.0),
    "instrumental_high_db": (-6.0, 6.0, 0.0),
    "target_lufs": (-30.0, -9.0, -18.0),
    "ceiling_db": (-6.0, -0.3, -1.5),
}
_BANDS = dict(rumble=-18.0, body=-7.0, mud=-6.0, mid=-8.0,
              presence=-12.0, sibilance=-15.0, air=-24.0)
_BLOCK = 131072


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} 必须是有限数值")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数值") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限数值")
    return result


def _choice(value, choices, name):
    if not isinstance(value, str):
        raise ValueError(f"无效的{name}")
    if value in choices:
        return value
    for key, label in choices.items():
        if value == label:
            return key
    raise ValueError(f"无效的{name}: {value}")


def _bound(value, low, high):
    return float(max(low, min(high, value)))


def validate_plan(plan):
    """Return a fresh, JSON-safe plan, using stable IDs and neutral defaults.

    Mapped Chinese labels are accepted on input; unknown keys, coercible strings,
    booleans, non-finite numbers and out-of-range edits are rejected.
    """
    if not isinstance(plan, Mapping):
        raise ValueError("歌曲方案必须是对象")
    if set(plan) - (set(_LIMITS) | {"target", "master"}):
        raise ValueError("歌曲方案包含未知字段")
    result = {
        "target": _choice(plan.get("target", "natural"), TARGETS, "歌曲目标"),
        "master": _choice(plan.get("master", "conservative"), MASTERING, "母带力度"),
    }
    for name, (low, high, default) in _LIMITS.items():
        value = _number(plan.get(name, default), name)
        if not low <= value <= high:
            raise ValueError(f"{name} 必须在 {low:g}–{high:g} 之间")
        result[name] = value
    return result


def _report(report):
    """Consume the small intelligence.metrics contract, not service or classifiers."""
    if not isinstance(report, Mapping):
        raise ValueError("需要音频测量报告")
    result = {}
    for name in ("lufs", "true_peak_db", "dynamic_db"):
        if name not in report:
            raise ValueError(f"测量报告缺少 {name}")
        result[name] = _number(report[name], name)
    if result["dynamic_db"] < 0:
        raise ValueError("dynamic_db 不能为负数")
    bands = report.get("bands_db")
    if not isinstance(bands, Mapping):
        raise ValueError("测量报告缺少 bands_db")
    result["bands_db"] = {
        key: _number(bands.get(key, default), "bands_db." + key)
        for key, default in _BANDS.items()
    }
    if "active_db" in report:
        result["active_db"] = _number(report["active_db"], "active_db")
    return result


def recommend(vocal_report, instrumental_report, original_report,
              target="natural", master="conservative"):
    """Suggest small editable balances and a material-dependent mastering target.

    Integrated levels and spectra are only advisory: these are not semantic
    separation scores or time-aligned masking measurements.
    """
    target = _choice(target, TARGETS, "歌曲目标")
    master = _choice(master, MASTERING, "母带力度")
    v, i, o = map(_report, (vocal_report, instrumental_report, original_report))
    # Desired integrated vocal/music difference, then modest tonal preferences.
    balance, low, mid, high, lift = {
        "natural": (-4.0, 0.0, 0.0, 0.0, 0.0),
        "forward": (-1.0, 0.0, -0.6, 0.0, 0.0),
        "impact": (-2.0, 0.6, -0.2, 0.15, 0.5),
        "clear": (-2.5, -0.4, -0.8, 0.35, 0.0),
        "full": (-4.0, 0.8, 0.0, -0.2, -0.25),
        "custom": (-4.0, 0.0, 0.0, 0.0, 0.0),
    }[target]
    vocal_gain = instrumental_gain = 0.0
    if min(v["lufs"], i["lufs"]) > -70:
        change = _bound((balance - (v["lufs"] - i["lufs"])) * 0.45, -3, 3)
        vocal_gain, instrumental_gain = 0.6 * change, -0.4 * change
        vb, ib = v["bands_db"], i["bands_db"]
        overlap = (i["lufs"] + ib["presence"]) - (v["lufs"] + vb["presence"])
        mid -= _bound((overlap + 3) * 0.10, 0, 1.5)
    if i["lufs"] > -70:
        ib, ob = i["bands_db"], o["bands_db"]
        low -= _bound((ib["body"] - ob["body"] - 2) * 0.12, 0, 1.0)
        mid -= _bound((ib["mud"] + 6) * 0.10, 0, 0.5)
        high -= _bound((ib["sibilance"] + 12) * 0.10, 0, 1.0)
    else:
        low = mid = high = 0.0

    source_level, source_peak, dynamics = o["lufs"], o["true_peak_db"], o["dynamic_db"]
    if source_level <= -70:
        active = [r for r in (v, i) if r["lufs"] > -70]
        if active:
            top = max(r["lufs"] for r in active)
            source_level = top + 10 * math.log10(sum(10 ** ((r["lufs"] - top) / 10) for r in active))
            source_peak = max(r["true_peak_db"] for r in active)
            dynamics = max(r["dynamic_db"] for r in active)
    boost, loudest, base_ceiling, budget = {
        "conservative": (1.0, -15.0, -1.5, 0.0),
        "standard": (2.5, -13.0, -1.2, 0.5),
        "strong": (4.0, -11.0, -1.0, 1.0),
        "custom": (1.0, -15.0, -1.5, 0.0),
    }[master]
    ceiling = base_ceiling - _bound((dynamics - 8) * 0.025, 0, 0.3)
    ceiling -= _bound(source_peak * 0.05, 0, 0.2)
    desired = source_level + boost + lift - max(0, dynamics - 8) * 0.08
    # Never recommend a large peak overshoot just to hit a fashionable LUFS value.
    feasible = source_level + max(0, ceiling - source_peak) + budget
    target_lufs = _bound(min(desired, feasible, loudest), -30, -9)
    return validate_plan(dict(
        target=target, master=master,
        vocal_gain_db=round(vocal_gain, 3),
        instrumental_gain_db=round(instrumental_gain, 3),
        instrumental_low_db=round(low, 3),
        instrumental_mid_db=round(mid, 3),
        instrumental_high_db=round(high, 3),
        target_lufs=round(target_lufs, 3), ceiling_db=round(ceiling, 3),
    ))


def vocal_params(report, style="经典喊麦", reference=None):
    """Conservative separated-vocal settings for the existing engine.process.

    No normalization/makeup, pitch, generated ambience, width change, saturation
    or second denoising pass. Reference matching changes only gentle EQ/dynamics.
    """
    r = _report(report)
    if isinstance(style, str):
        if style not in PRESETS:
            raise ValueError("未知人声风格")
        style = PRESETS[style]
    elif not isinstance(style, Mapping):
        raise ValueError("人声风格必须是预设名称或参数对象")
    p = engine.normalize(style)
    b = r["bands_db"]
    for band, limit in (("body", 1.2), ("mud", 1.8), ("presence", 1.5), ("air", 1.0)):
        adjustment = (_BANDS[band] - b[band]) * (0.12 if band != "air" else 0.05)
        p[band + "_db"] = _bound(p[band + "_db"] * 0.25 + adjustment, -limit, limit)
    p["highpass_hz"] = _bound(35 + max(0, b["rumble"] + 22) * 1.2, 30, 70)
    p["threshold_db"] = _bound(r.get("active_db", r["lufs"]) + 3, -55, -6)
    p["ratio"] = _bound(1.05 + max(0, r["dynamic_db"] - 3) * 0.035, 1.05, 1.8)
    p["attack_ms"] = _bound(22 + r["dynamic_db"] * 0.5, 22, 38)
    p["release_ms"] = _bound(110 + r["dynamic_db"] * 3, 110, 180)
    p["knee_db"] = 6.0
    p["deess"] = _bound((b["sibilance"] + 22) * 0.012, 0, 0.22)
    if reference is not None:
        ref = _report(reference)
        if ref["lufs"] <= -70:
            raise ValueError("参考音频低于响度门限")
        for band, limit in (("body", 1.2), ("mud", 1.8), ("presence", 1.5), ("air", 1.0)):
            delta = _bound((ref["bands_db"][band] - b[band]) * 0.10, -0.6, 0.6)
            p[band + "_db"] = _bound(p[band + "_db"] + delta, -limit, limit)
        p["ratio"] = _bound(p["ratio"] + (r["dynamic_db"] - ref["dynamic_db"]) * 0.01, 1.05, 1.8)
    for key in ("automation", "pitch_edits", "tail_regions", "pitch_regions", "tail_edits"):
        p.pop(key, None)
    p.update(denoise=0.0, hum_hz=0, pitch_strength=0.0, semitones=0.0,
             makeup_db=0.0, drive=0.0, reverb=0.0, delay=0.0, feedback=0.0,
             dry=1.0, width=1.0, tail_times=[])
    p["disabled"] = list(dict.fromkeys(p["disabled"] + [
        "denoise", "pitch", "saturate", "space", "stereo", "master",
    ]))
    return engine.normalize(p)


def _rate(sr):
    rate = _number(sr, "采样率")
    if not 8000 <= rate <= 192000 or not rate.is_integer():
        raise ValueError("需要 8–192 kHz 整数采样率")
    return int(rate)


def _audio(audio, sr, cancel):
    check(cancel)
    if np.iscomplexobj(audio):
        raise ValueError("音频不能包含复数采样")
    with np.errstate(over="ignore", invalid="ignore"):
        x = as_audio(audio, sr)
    for start in range(0, len(x), _BLOCK):
        check(cancel)
        if not np.isfinite(x[start:start + _BLOCK]).all():
            raise ValueError("音频包含非有限采样值")
    return x


def _gain(x, gain_db, cancel, *, owned=False):
    if gain_db == 0:
        check(cancel)
        return x
    y = x if owned else np.empty_like(x)
    gain = 10 ** (gain_db / 20)
    for start in range(0, len(x), _BLOCK):
        check(cancel)
        with np.errstate(over="ignore", invalid="ignore"):
            np.multiply(x[start:start + _BLOCK], gain, out=y[start:start + _BLOCK])
        if not np.isfinite(y[start:start + _BLOCK]).all():
            raise ValueError("增益处理产生非有限采样值")
    check(cancel)
    return y


def process_stems(vocal, instrumental, sr, plan, cancel=None):
    """Gain vocal, EQ/gain music; leave alignment, summing and tails to Studio.

    Neutral float32 2-D inputs are returned by identity. Changed inputs are never
    mutated; EQ's owned output is gained in-place, avoiding another full copy.
    Each stem keeps its own length, including a longer instrumental ending.
    """
    check(cancel)
    p, sr = validate_plan(plan), _rate(sr)
    v, i = _audio(vocal, sr, cancel), _audio(instrumental, sr, cancel)
    gains = [p["instrumental_" + band + "_db"] for band in ("low", "mid", "high")]
    changed = any(gains)
    if changed:
        # Reuse engine EQ sections, not its vocal high-pass or unused mud band.
        eq = dict(highpass_hz=20, body_hz=120, body_db=gains[0],
                  mud_hz=350, mud_db=0, presence_hz=2200, presence_db=gains[1],
                  air_hz=7000, air_db=gains[2], eq_q=0.7)
        sections = engine.eq_sos(sr, eq)[[idx for idx, gain in zip((1, 3, 4), gains) if gain]]
        i = engine.filter_audio(i, sections, cancel)
        i = _audio(i, sr, cancel)
    v = _gain(v, p["vocal_gain_db"], cancel)
    i = _gain(i, p["instrumental_gain_db"], cancel, owned=changed)
    check(cancel)
    return v, i


def master_mix(audio, sr, plan, cancel=None):
    """Peak-safe final master of the caller's Studio render, without a new mixer.

    Conservative/custom use only a constant gain, preserving all dynamics. Other
    modes allow at most 0.65/1.25 dB of crest-adaptive limiting; very transient
    material gets none. Targets are aspirations, not permission for huge makeup.
    """
    check(cancel)
    p, sr = validate_plan(plan), _rate(sr)
    x = _audio(audio, sr, cancel)
    level = loudness(x, sr, cancel)
    peak = true_peak(x, sr, cancel)
    check(cancel)
    if peak == 0:
        return x
    peak_db = 20 * math.log10(peak)
    headroom = p["ceiling_db"] - peak_db
    if level <= -70:
        return _gain(x, min(0.0, headroom - 0.001) if headroom < 0 else 0.0, cancel)
    crest = max(0.0, peak_db - level)
    max_boost, budget = {
        "conservative": (2.0, 0.0), "standard": (3.0, 0.65),
        "strong": (4.5, 1.25), "custom": (2.0, 0.0),
    }[p["master"]]
    max_boost = max(0.5, max_boost - max(0, crest - 12) * 0.15)
    budget *= _bound((18 - crest) / 12, 0, 1)
    desired = p["target_lufs"] - level
    if abs(desired) < 1e-6 and headroom >= 0:
        return x
    gain = min(desired, max_boost, headroom - 0.001 + budget)
    if gain <= headroom:
        return _gain(x, gain, cancel)
    # engine.master's normal 4 dB budget is constrained by this measured target.
    result = engine.master(x, sr, dict(target_lufs=level + gain, ceiling_db=p["ceiling_db"]), cancel)
    check(cancel)
    return _audio(result, sr, cancel)


def separation_evidence(original, vocal, inst, sr, cancel=None):
    """Objective length/reconstruction evidence, NOT semantic separation quality.

    Missing tails are zero-extended only for this measurement. A perfect sum can
    still have severe vocal leakage; no confidence/quality score is inferred.
    """
    check(cancel)
    sr = _rate(sr)
    sources = [_audio(x, sr, cancel) for x in (original, vocal, inst)]
    lengths = [len(x) for x in sources]
    frames, channels = max(lengths), max(x.shape[1] for x in sources)
    error_energy = original_energy = 0.0
    for start in range(0, frames, _BLOCK):
        check(cancel)
        residual = np.zeros((min(_BLOCK, frames - start), channels), dtype=np.float64)
        for index, source in enumerate(sources):
            block = source[start:start + _BLOCK]
            if not len(block):
                continue
            if index == 0:
                residual[:len(block)] += block
                original_energy += float(np.sum(block.astype(np.float64) ** 2)) * channels / block.shape[1]
            else:
                residual[:len(block)] -= block
        error_energy += float(np.einsum("ij,ij->", residual, residual))
    rms = math.sqrt(error_energy / (frames * channels))
    relative = None
    if error_energy == 0:
        relative = -120.0
    elif original_energy > 0:
        relative = _bound(10 * math.log10(error_energy / original_energy), -120, 120)
    match = len(set(lengths)) == 1
    check(cancel)
    return dict(
        original_frames=lengths[0], vocal_frames=lengths[1], instrumental_frames=lengths[2],
        comparison_frames=frames, overlap_frames=min(lengths), length_match=match,
        reconstruction_error_db=relative,
        reconstruction_rms_db=max(-120.0, 20 * math.log10(max(1e-30, rms))),
        warnings=[] if match else ["分轨长度不同；重建测量对缺失尾部补零，混音请保留完整时间线。"],
        note="仅检查长度与分轨相加重建误差；不能据此判断人声泄漏或分离质量。",
    )
