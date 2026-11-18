import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from scipy.io import wavfile

from vox import engine
from vox.segments import analyze_segments, recommend_automation, validate_automation

SR = 16000


def harmonic(hz, seconds, amp=0.2):
    t = np.arange(round(seconds * SR)) / SR
    return amp * (
        np.sin(2 * np.pi * hz * t)
        + 0.60 * np.sin(4 * np.pi * hz * t)
        + 0.34 * np.sin(6 * np.pi * hz * t)
    )


def stereo(x):
    return np.column_stack((x, x)).astype("f")


def only(stage, **updates):
    return dict(
        engine.PRESETS["经典喊麦"],
        disabled=[s for s in engine.STAGES if s != stage],
        **updates,
    )


def measure(x):
    r = engine.analyze(x, SR)
    r["segments"] = analyze_segments(x, SR, r)
    return r


def test_segments_partition_silence_note_and_burst():
    x = np.r_[
        np.zeros(SR // 2),
        harmonic(190, 1.6, 0.08),
        harmonic(380, 0.22, 0.55),
        harmonic(190, 0.4, 0.08),
        np.zeros(SR // 2),
    ]
    r = measure(stereo(x))
    parts = r["segments"]
    assert parts[0]["label"] == "静音" and parts[-1]["label"] == "静音"
    assert parts[0]["start"] == 0 and parts[-1]["end"] == len(x) / SR
    assert all(a["end"] == b["start"] for a, b in zip(parts, parts[1:]))
    assert any(s["sustained"] and s["type"] in ("普通演唱", "旋律型喊麦") for s in parts)
    assert any(s["burst"] and s["level_db"] > -12 and s["type"] == "高强度喊唱" for s in parts)
    assert all(s["evidence"] and s["limitations"] and 0 <= s["confidence"] <= 1 for s in parts)
    assert all(set(s["bands_db"]) == set(r["bands_db"]) for s in parts)
    assert json.loads(json.dumps(parts, allow_nan=False)) == parts


def test_uncertain_noise_uses_conservative_limits():
    noise = np.random.default_rng(24).normal(0, 0.035, (SR * 2, 2)).astype("f")
    r = measure(noise)
    p = engine.recommend(r, "旋律喊麦")
    assert all(s["type"] == "未知类型" for s in r["segments"])
    assert all(
        not c["pitch_safe"] and c["space_scale"] <= 0.3 and c["denoise_scale"] <= 0.3
        for c in p["automation"]
    )
    # Explicit manual speech mode never quantizes stable periodic passages.
    r = measure(stereo(harmonic(220, 1.2)))
    r["classification"] = "语音喊麦"
    assert not any(c["pitch_safe"] for c in recommend_automation(r))


def test_rhythmic_and_mixed_candidates_follow_observable_cues():
    seconds = 5
    t = np.arange(SR * seconds) / SR
    voice = harmonic(190, seconds, 0.3)
    pulses = voice * (0.60 + 0.35 * np.sin(2 * np.pi * 6 * t))
    rap = measure(stereo(pulses))
    assert rap["bpm"] and any(
        s["type"] == "Rap" and s["label"] == "快速咬字" for s in rap["segments"]
    )
    harmony = measure(np.column_stack((voice, harmonic(250, seconds, 0.3))).astype("f"))
    assert any(
        s["type"] == "混合人声" and s["dual_pitch"] and s["confidence"] < 0.6
        for s in harmony["segments"]
    )
    drums = (
        np.random.default_rng(3).normal(0, 0.19, (len(t), 2))
        * np.maximum(0, np.sin(4 * np.pi * t))[:, None] ** 4
    )
    percussion = measure(drums.astype("f"))
    assert any(s["type"] == "纯伴奏" and s["confidence"] < 0.6 for s in percussion["segments"])
    mixed = measure((voice[:, None] + drums * 2.8).astype("f"))
    assert any(s["type"] == "人声加伴奏" for s in mixed["segments"])
    assert all(
        not c["pitch_safe"]
        for s, c in zip(mixed["segments"], recommend_automation(mixed))
        if s["type"] == "人声加伴奏"
    )


def test_plosive_and_sibilant_frequency_selective_reduction():
    t = np.arange(SR * 3) / SR
    baseline = 0.04 * harmonic(210, 3.0)
    plosive = (t > 0.7) & (t < 0.85)
    hiss = (t > 1.6) & (t < 1.95)
    x = (
        baseline
        + plosive * 0.6 * np.sin(2 * np.pi * 50 * t)
        + hiss * 0.4 * np.sin(2 * np.pi * 6500 * t)
    )
    r = measure(stereo(x))
    controls = recommend_automation(r)
    assert any(c["highpass_delta_hz"] > 0 for c in controls)
    assert any(c["sibilance_delta_db"] < -0.5 for c in controls)
    base = only("eq", highpass_hz=45)
    plain = engine.process(stereo(x), SR, base)
    # Isolate the newly proposed specific protections from the broad-band EQ.
    protected = [
        {
            k: v
            for k, v in c.items()
            if k in ("start", "end", "highpass_delta_hz", "sibilance_delta_db")
        }
        for c in controls
    ]
    y = engine.process(stereo(x), SR, dict(base, automation=protected))
    assert np.std(y[plosive]) < 0.9 * np.std(plain[plosive])
    assert np.std(y[hiss]) < 0.95 * np.std(plain[hiss])


def test_real_speech_evidence_and_audit_are_reproducible():
    sr, x = wavfile.read(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")
    assert sr == SR
    x = stereo(x)
    before = x.copy()
    r = measure(x)
    assert any(s["type"] == "普通语音喊麦" for s in r["segments"])
    assert any(s["active"] and s["voiced_fraction"] > 0.4 for s in r["segments"])
    p = engine.recommend(r)
    audit = {}
    y = engine.process(x, sr, p, audit=audit)
    assert np.array_equal(x, before) and y.shape == x.shape and not np.array_equal(x, y)
    assert audit["eq"]["before_bands_db"] != audit["eq"]["after_bands_db"]
    assert "eq" in audit["changed_stages"] and audit["compression"]["curve"]
    assert audit["compression"]["max_gr_db"] == max(gr for _, gr in audit["compression"]["curve"])
    assert np.array_equal(y, engine.process(x, sr, json.loads(json.dumps(p))))
    json.dumps(audit, allow_nan=False)


def test_region_eq_changes_only_target_range_with_smooth_transitions():
    t = np.arange(SR * 2) / SR
    x = stereo(0.2 * np.sin(2 * np.pi * 330 * t))
    base = only("eq", body_db=0, mud_db=0, presence_db=0, air_db=0)
    original = engine.process(x, SR, base)
    automation = [
        dict(start=0.5, end=1.0, mud_delta_db=-4),
        dict(start=1.0, end=1.5, mud_delta_db=3),
    ]
    y = engine.process(x, SR, dict(base, automation=automation))

    def gain(t):
        sl = slice(int((t - 0.035) * SR), int((t + 0.035) * SR))
        return 20 * np.log10(np.std(y[sl]) / np.std(original[sl]))

    assert abs(gain(0.2)) < 0.005 and abs(gain(1.8)) < 0.005
    assert gain(0.75) == pytest.approx(-4, abs=0.06) and gain(1.25) == pytest.approx(3, abs=0.06)
    # The steepest transition around the join must stay inside the natural
    # derivative of the louder, stationary sine, with a small slope allowance.
    around = np.diff(y[round(0.97 * SR) : round(1.03 * SR), 0])
    loud = np.diff(y[round(1.10 * SR) : round(1.20 * SR), 0])
    assert np.abs(around).max() < 1.02 * np.abs(loud).max()


def test_transient_preservation_and_actual_reduction_log():
    x = stereo(np.r_[harmonic(300, 0.6, 0.012), harmonic(300, 1, 0.38)])
    p = only("compress", threshold_db=-26, attack_ms=3, knee_db=0, ratio=5, makeup_db=0)
    region = dict(start=0, end=1.6, ratio_scale=1.0, threshold_delta_db=0)
    protected = dict(p, automation=[dict(region, transient_protect=1)])
    plain = dict(p, automation=[dict(region, transient_protect=0)])
    audit = {}
    y = engine.process(x, SR, protected, audit=audit)
    z = engine.process(x, SR, plain)
    onset = slice(round(0.603 * SR), round(0.620 * SR))
    assert np.std(y[onset]) > np.std(z[onset]) * 1.3
    assert np.std(y[-SR // 4 :]) == pytest.approx(np.std(z[-SR // 4 :]), rel=0.002)
    measured = -20 * np.log10(np.std(y[-SR // 4 :]) / np.std(x[-SR // 4 :]))
    assert measured == pytest.approx(audit["compression"]["p95_gr_db"], abs=0.5)
    assert audit["warnings"] and audit["compression"]["over_6db_fraction"] > 0.3


def test_scoped_noise_mix_shares_one_stationary_noise_profile():
    n = SR * 3
    x = np.random.default_rng(6).normal(0, 0.009, (n, 2)).astype("f")
    x[SR : 2 * SR] += stereo(harmonic(240, 1.0))
    p = only(
        "denoise",
        denoise=1.0,
        automation=[
            dict(start=0, end=1.0, denoise_scale=0),
            dict(start=1.0, end=3.0, denoise_scale=1),
        ],
    )
    audit = {}
    y = engine.process(x, SR, p, audit=audit)
    assert np.array_equal(y[: SR // 2], x[: SR // 2])
    assert np.std(y[-SR // 2 :]) < np.std(x[-SR // 2 :]) * 0.85
    assert audit["denoise"]["quiet_delta_db"] < 0


def test_cancel_malformed_timeline_and_legacy_render():
    x = stereo(harmonic(220, 0.25))
    e = Event()
    e.set()
    with pytest.raises(InterruptedError):
        analyze_segments(x, SR, {}, e)
    for bad in (
        [{"start": 0.4, "end": 0.1}],
        [dict(start=0, end=1), dict(start=0.9, end=2)],
        [dict(start=0, end=1, ratio_scale=float("nan"))],
    ):
        with pytest.raises(ValueError):
            validate_automation(bad)
    p = only("eq")
    assert np.array_equal(
        engine.process(x, SR, p), engine.filter_audio(x, engine.eq_sos(SR, p), None)
    )
