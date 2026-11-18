"""Objective audio checks. The Mandarin fixture is recorded speech; tones isolate effects."""

import hashlib
import json
from pathlib import Path
from threading import Event
import numpy as np
import pytest
from scipy import signal
from scipy.io import wavfile
from vox import engine
from vox.analysis import pitch_track, true_peak
from vox.presets import PRESETS, STAGES

SR = 44100


def tone(frequency, seconds, amplitude=0.3):
    t = np.arange(round(SR * seconds)) / SR
    mono = amplitude * np.sin(2 * np.pi * frequency * t)
    return np.column_stack((mono, mono)).astype(np.float32)


def isolated(stage, **updates):
    return {**PRESETS["经典喊麦"], **updates, "disabled": [k for k in STAGES if k != stage]}


@pytest.fixture(scope="module")
def speech():
    rate, x = wavfile.read(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")
    x = (
        signal.resample_poly(x, 441, 160)
        if rate == 16000
        else signal.resample(x, round(len(x) * SR / rate))
    )
    return np.column_stack((x, x)).astype(np.float32)


def test_meter_calibration():
    # Equal-channel 1 kHz sine at -20 dBFS peak is close to -20 LUFS stereo.
    x = tone(1000, 2, 0.1)
    r = engine.analyze(x, SR)
    assert r["peak_db"] == pytest.approx(-20, abs=0.02)
    assert r["rms_db"] == pytest.approx(-23.0103, abs=0.02)
    assert r["lufs"] == pytest.approx(-20, abs=0.13)
    assert -20.1 <= r["true_peak_db"] <= -19.9
    assert r["clipped_samples"] == 0


def test_recorded_speech_factory_recipes(speech):
    x = speech[SR : SR * 3]
    before = x.copy()
    report = engine.analyze(x, SR)
    signatures = set()
    assert len(PRESETS) == 18
    for name in PRESETS:
        p = engine.recommend(report, name)
        y = engine.process(x, SR, p)
        assert y.shape == x.shape and y.dtype == np.float32 and np.isfinite(y).all()
        assert np.max(abs(x - y)) > 0.005
        assert 20 * np.log10(true_peak(y, SR)) <= p["ceiling_db"] + 0.015
        signatures.add(hashlib.sha256(y.tobytes()).digest())
    assert len(signatures) == 18
    assert np.array_equal(before, x)
    json.dumps(report, allow_nan=False)


def test_measured_adaptation_reference(speech):
    dry = speech[SR * 2 : SR * 4] * (0.5 / np.max(np.abs(speech)))
    hot = engine.analyze(dry, SR)
    quiet = engine.analyze(dry * 0.2, SR)
    a = engine.recommend(hot)
    b = engine.recommend(quiet)
    assert b["threshold_db"] < a["threshold_db"] - 5
    bright = engine.analyze(
        signal.sosfilt(signal.butter(2, 2000, fs=SR, btype="highpass", output="sos"), dry, axis=0), SR
    )
    matched = engine.recommend(hot, PRESETS["经典喊麦"], bright)
    assert matched["presence_db"] > a["presence_db"] and matched["body_db"] < a["body_db"]
    with pytest.raises(ValueError):
        engine.recommend(hot, "经典喊麦", engine.analyze(dry * 0, SR))


def test_tail_sends_are_localized():
    x = np.vstack(
        (tone(210, 0.45), np.zeros((SR // 2, 2)), tone(260, 0.45), np.zeros((SR // 2, 2)))
    ).astype("f")
    report = engine.analyze(x, SR)
    assert any(abs(t - 0.45) < 0.04 for t in report["tail_times"])
    params = isolated("space", reverb=0, delay=0.7, delay_ms=300, wet_width=1, tail_times=[0.45])
    wet = engine.process(x, SR, params)
    assert np.allclose(wet[: SR // 2], x[: SR // 2])
    assert np.max(abs(wet[round(0.55 * SR) : round(0.72 * SR), 0])) > 0.05
    assert np.max(abs(wet[round(0.55 * SR) : round(0.72 * SR), 1])) < 1e-5


def test_reverb_tail_survives_silence():
    x = np.vstack((tone(900, 0.3), np.zeros((SR, 2)))).astype("f")
    wet = engine.process(x, SR, isolated("space", reverb=0.5, delay=0))
    assert np.max(abs(wet[round(0.32 * SR) : round(0.44 * SR)])) > 0.001


def test_highpass_comp_and_deess():
    bass = tone(40, 1)
    y = engine.process(bass, SR, isolated("eq", highpass_hz=180))
    assert np.std(y[SR // 2 :]) < np.std(bass) * 0.15
    x = np.vstack((tone(1000, 0.5, 0.06), tone(1000, 0.5, 0.6)))
    y = engine.process(x, SR, isolated("compress", threshold_db=-22, ratio=5, knee_db=0, makeup_db=0))
    assert np.std(y[-SR // 5 :]) < np.std(x[-SR // 5 :]) * 0.33
    assert np.std(y[: SR // 4]) > np.std(x[: SR // 4]) * 0.96
    x = tone(7400, 0.8)
    y = engine.process(x, SR, isolated("deess", deess=0.95))
    assert np.std(y) < np.std(x) * 0.6


def test_stationary_denoise_and_harmonics(speech):
    n = len(speech)
    noise = np.random.default_rng(9).normal(0, np.std(speech) * 0.15, (n, 2)).astype("f")
    x = noise.copy()
    x[SR:-SR] += speech[SR:-SR]
    y = engine.process(x, SR, isolated("denoise", denoise=1.0))
    assert np.std(y[1000 : SR // 2]) < 0.84 * np.std(noise[1000 : SR // 2])
    clean = tone(900, 0.5, 0.6)
    wet = engine.process(clean, SR, isolated("saturate", drive=0.85))
    spectrum = abs(np.fft.rfft(wet[:, 0])) / len(wet)
    assert spectrum[1350] > 0.005  # third harmonic at 2700 Hz for a 0.5 s FFT


def test_pitch_and_unvoiced_bypass():
    x = tone(226, 1.5)
    y = engine.process(x, SR, isolated("pitch", pitch_strength=1, semitones=0))
    _, hz = pitch_track(y, SR)
    assert np.median(hz) == pytest.approx(220, abs=1)
    assert np.array_equal(engine.process(x, SR, isolated("pitch", pitch_strength=0)), x)
    s = tone(226, 1, 0)
    assert np.array_equal(engine.process(s, SR, isolated("pitch", pitch_strength=1)), s)


def test_stereo_and_limiter():
    x = tone(300, 1, 0.95)
    x[:, 1] += tone(420, 1, 0.3)[:, 0]
    mono = engine.process(x, SR, isolated("stereo", width=0))
    assert np.array_equal(mono[:, 0], mono[:, 1])
    y = engine.process(x, SR, isolated("master", target_lufs=-10, ceiling_db=-3))
    assert 20 * np.log10(true_peak(y, SR)) < -2.99
    assert engine.analyze(y, SR)["clipped_samples"] == 0


def test_peak_guard_for_partial_terminal_block_and_reordered_chain():
    x = np.zeros((SR + 500, 2), np.float32)
    x[-7] = 1.5
    y = engine.process(x, SR, isolated("master", ceiling_db=-3))
    assert 20 * np.log10(true_peak(y, SR)) <= -2.99
    p = dict(
        PRESETS["Rap"],
        order=["master", "eq"],
        disabled=[s for s in STAGES if s not in ("eq", "master")],
        body_db=9,
        body_hz=180,
        target_lufs=-9,
        ceiling_db=-3,
    )
    y = engine.process(tone(180, 2, 0.9), SR, p)
    assert 20 * np.log10(true_peak(y, SR)) <= -2.99


def test_hum_evidence_controls_notch():
    x = tone(50, 2.4, 0.07) + tone(900, 2.4, 0.03)
    report = engine.analyze(x, SR)
    assert report["hum_hz"] == 50
    p = engine.recommend(report)
    assert p["hum_hz"] == 50 and p["denoise"] > 0
    y = engine.process(x, SR, isolated("denoise", hum_hz=50, denoise=1))
    tail = y[SR : 2 * SR, 0]
    s = abs(np.fft.rfft(tail))
    assert s[50] < s[900] * 0.1


def test_tail_reverb_only_and_tempo_division():
    x = np.vstack((tone(350, 0.5), np.zeros((SR, 2)))).astype("f")
    p = isolated("space", reverb=0.5, delay=0, reverb_send="Tails", tail_times=[])
    assert np.allclose(engine.process(x, SR, p), x)
    wet = engine.process(x, SR, dict(p, tail_times=[0.5]))
    assert np.max(abs(wet[SR // 2 :])) > 0.01
    params = isolated(
        "space",
        reverb=0,
        delay=0.7,
        delay_type="Tempo",
        tempo_bpm=120,
        beat_fraction=1,
        feedback=0,
        tail_times=[0.5],
    )
    assert np.max(abs(engine.process(x, SR, params)[round(0.85 * SR) : SR])) > 0.1


def test_cancellation_short_silence_and_invalid_inputs():
    event = Event()
    event.set()
    x = tone(1000, 0.1)
    with pytest.raises(InterruptedError):
        engine.process(x, SR, PRESETS["Rap"], event)
    with pytest.raises(InterruptedError):
        engine.analyze(x, SR, event)
    z = np.zeros((2, 2), np.float32)
    report = engine.analyze(z, SR)
    assert report["lufs"] == -120 and not report["tail_times"]
    assert np.array_equal(engine.process(z, SR, engine.recommend(report)), z)
    with pytest.raises(ValueError):
        engine.analyze(np.full_like(z, np.nan), SR)
    with pytest.raises(ValueError):
        engine.process(z, SR, {"order": ["eq", "eq"]})
