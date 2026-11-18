import json
from threading import Event

import numpy as np
import pytest

from vox.acoustics import compare_lines, extra_features, report_lines
from vox.analysis import analyze

SR = 16000


def measure(x):
    report = analyze(x, SR)
    report.update(extra_features(x, SR, report))
    json.dumps(report, allow_nan=False)
    return report


def test_plateaus_cross_chunk_boundary_and_overs_are_distinct():
    x = np.zeros((30000, 2), np.float32)
    boundary = 160 * 160
    x[boundary - 2 : boundary + 9, 0] = 1.0
    x[1900, 1] = 1.4
    x[2020:2023, 1] = -32767 / 32768
    m = measure(x)["acoustics"]
    assert m["rail_plateau_runs"] == 2
    assert m["over_full_samples"] == 1
    assert m["near_full_samples"] == 15


def test_tone_stability_and_spectrum():
    t = np.arange(2 * SR) / SR
    m = measure(0.4 * np.sin(2 * np.pi * 220 * t))["acoustics"]
    assert 210 <= m["centroid_hz"] <= 230
    assert 210 <= m["rolloff85_hz"] <= 240
    assert abs(m["pitch_p10_hz"] - 220) < 2
    assert m["stable_pitch_runs"] == 1 and m["longest_stable_s"] > 1.5
    assert m["repeat_delay_ms"] is None


def test_regular_attacks_and_repeated_broadband_shape():
    x = np.zeros(SR * 8, np.float32)
    rng = np.random.default_rng(19)
    for onset in np.arange(0.25, 7.7, 0.5):
        block = rng.normal(size=560) * np.hanning(560) * 0.07
        index = round(onset * SR)
        x[index : index + 560] = block
        x[index + 2400 : index + 2960] = 0.35 * block
    m = measure(x)["acoustics"]
    assert 118 <= m["pulse_bpm"] <= 122
    assert abs(m["repeat_delay_ms"] - 150) <= 2
    assert m["repeat_support"] >= 3


def test_reproducible_falling_tail_and_insufficient_evidence():
    rng = np.random.default_rng(10)
    x = np.zeros(SR * 5, np.float32)
    endings = []
    for start in (SR // 2, 2 * SR, SR * 7 // 2):
        t = np.arange(round(0.8 * SR)) / SR
        x[start : start + len(t)] = 0.16 * rng.normal(size=len(t)) * 10 ** (-48 * t / 20)
        endings.append(start / SR + 0.3)
    report = {"tail_times": endings}
    report.update(extra_features(x, SR, report))
    m = report["acoustics"]
    assert m["decay_count"] == 3 and abs(m["decay20_s"] - 20 / 48) < 0.07
    silence = measure(np.zeros((250, 2), np.float32))
    assert silence["acoustics"]["centroid_hz"] is None
    assert silence["acoustics"]["repeat_delay_ms"] is None
    assert silence["acoustics"]["pulse_bpm"] is None
    assert silence["acoustics"]["decay20_s"] is None
    assert any("未知" in line for line in report_lines(silence))
    assert any("差异未知" in line for line in compare_lines(silence, report))


def test_comparison_direction_and_cancellation():
    assert any("+3.0 LU" in line for line in compare_lines({"lufs": -13}, {"lufs": -16}))
    stop = Event()
    stop.set()
    with pytest.raises(InterruptedError):
        extra_features(np.zeros(120), SR, {}, stop)
