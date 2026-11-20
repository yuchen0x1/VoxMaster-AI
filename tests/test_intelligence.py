import json
from copy import deepcopy
from threading import Event

import numpy as np
import pytest

from vox import (
    acoustics,
    analysis,
    audioio,
    engine,
    intelligence,
    quality,
    reference,
    segments,
)


SR = audioio.WORK_RATE


def tone(sr, hz, duration):
    t = np.arange(round(sr * duration)) / sr
    return np.sin(2 * np.pi * hz * t).astype(np.float32)


def test_measure_adds_routing_without_changing_service_values():
    sine = tone(SR, 375, 1.8)
    sine[SR // 2 : SR] = 0
    samples = np.column_stack((0.33 * sine, 0.05 * sine))
    before = samples.copy()

    # The pre-intelligence service.measure sequence (before delegating).
    legacy = engine.analyze(samples, SR)
    legacy.update(acoustics.extra_features(samples, SR, legacy))
    legacy["segments"] = segments.analyze_segments(samples, SR, legacy)
    legacy.update(quality.quality_metrics(samples, SR, legacy))
    legacy["role_space"] = reference.measure_role_space(samples, SR, legacy)
    report = intelligence.measure(samples, SR)
    routing = report.pop("routing")

    assert report == legacy
    assert np.array_equal(samples, before)
    assert (
        legacy["classification"] == "疑似人声与伴奏混合"
    )  # Actually just one panned tone.
    assert routing["mode"] == "manual"
    assert routing["recommended"] == "unknown"
    assert routing["reason"] == "acoustic_cues_not_role_specific"
    assert any(
        cue["kind"] == "stable_pitch" and cue["count"] > 0
        for cue in routing["evidence"]
    )


@pytest.mark.parametrize("gain", [0.005, 0.95])
def test_level_and_stereo_spread_do_not_assign_a_role(gain):
    rng = np.random.default_rng(21)
    noise = rng.uniform(-gain, gain, SR).astype(np.float32)
    report = intelligence.measure(np.column_stack((noise, -noise)), SR)

    assert report["side_fraction"] > 0.99
    assert report["routing"] == {
        "mode": "manual",
        "recommended": "unknown",
        "reason": "no_role_cues",
        "evidence": [],
    }


def test_different_channel_periodicities_are_evidence_not_a_role():
    samples = 0.3 * np.column_stack((tone(SR, 220, 0.8), tone(SR, 277, 0.8)))
    routing = intelligence.measure(samples, SR)["routing"]
    assert routing["recommended"] == "unknown"
    assert {"kind": "different_channel_periodicities", "count": 1} in routing[
        "evidence"
    ]


def test_inspect_mono_source_keeps_decoded_bus_values(tmp_path):
    path = tmp_path / "mono.wav"
    audioio.encode(
        path, 0.2 * tone(48000, 375, 0.8), 48000, 24, output_rate=48000, channels=1
    )
    samples, meta = audioio.decode(path)
    report = intelligence.measure(samples, audioio.WORK_RATE)
    original = deepcopy(report)
    result = intelligence.inspect_file(report, meta)

    assert result is not report and report == original
    assert result["source_metadata"] == meta and result["source_metadata"] is not meta
    assert (meta["channels"], meta["sample_rate"], meta["bit_depth"]) == (1, 48000, 24)
    assert result["duration"] == meta["duration"]
    assert (result["channels"], result["sample_rate"]) == (2, audioio.WORK_RATE)
    assert result["stereo_correlation"] == pytest.approx(1)
    assert result["lufs"] == original["lufs"]
    assert result["inspection"]["measurement_basis"] == "decoded_pcm"
    assert result["inspection"]["channel_layout"] == "mono"
    assert result["inspection"]["stereo_evidence"] == "duplicated_mono"
    assert "classification" in result["inspection"]["estimates"]
    assert "vocal_accompaniment_balance" in result["inspection"]["unknown"]
    json.dumps(result, allow_nan=False)


def test_inspect_keeps_unknown_metadata_and_distinguishes_effect_estimates():
    report = {"channels": 2, "acoustics": {"repeat_delay_ms": 110, "decay20_s": 0.26}}
    result = intelligence.inspect_file(report, {"codec": "aac", "bit_depth": None})
    inspection = result["inspection"]

    assert result["source_metadata"]["bit_depth"] is None
    assert inspection["channel_layout"] == "unknown"
    assert inspection["stereo_evidence"] == "unavailable"
    assert inspection["level_status"] == "unknown"
    assert "not proof" in inspection["estimates"]["acoustics.repeat_delay_ms"]
    assert "not reverb" in inspection["estimates"]["acoustics.decay20_s"]
    assert "effect_settings" in inspection["unknown"]


def test_silent_clip_reports_meter_floor_not_a_source_role():
    samples = np.zeros((200, 2), dtype=np.float32)
    report = intelligence.inspect_file(
        intelligence.measure(samples, SR), {"channels": 2}
    )
    meters = intelligence.metrics(samples, SR)

    assert report["routing"]["recommended"] == "unknown"
    assert report["routing"]["evidence"] == []
    assert report["inspection"]["level_status"] == "below_loudness_gate"
    assert meters["lufs"] == meters["true_peak_db"] == meters["rms_db"] == -120.0
    assert set(meters["bands_db"].values()) == {-120.0}
    assert meters["dynamic_db"] == meters["side_fraction"] == 0
    assert meters["stereo_correlation"] is None
    json.dumps(meters, allow_nan=False)


def test_metrics_without_pitch_uses_expected_units_and_keeps_antiphase_power(
    monkeypatch,
):
    def unexpected(*args, **kwargs):
        pytest.fail(
            "Song meters should not run analysis, pitch, segments or role-space"
        )

    monkeypatch.setattr(intelligence.engine, "analyze", unexpected)
    monkeypatch.setattr(analysis, "pitch_track", unexpected)
    monkeypatch.setattr(intelligence, "extra_features", unexpected)
    monkeypatch.setattr(intelligence, "analyze_segments", unexpected)
    monkeypatch.setattr(intelligence, "measure_role_space", unexpected)
    sr = 48000
    lead = 0.5 * tone(sr, 375, 1.0)
    audio = np.column_stack((lead, -lead))
    meters = intelligence.metrics(audio, sr)

    assert (meters["sample_rate"], meters["channels"], meters["duration"]) == (
        sr,
        2,
        1.0,
    )
    assert meters["rms_db"] == pytest.approx(20 * np.log10(0.5 / np.sqrt(2)), abs=0.01)
    assert meters["peak_db"] == pytest.approx(-6.02, abs=0.01)
    assert meters["true_peak_db"] == pytest.approx(meters["peak_db"], abs=0.05)
    assert meters["lufs"] == pytest.approx(analysis.loudness(audio, sr))
    assert meters["stereo_correlation"] == pytest.approx(-1)
    assert meters["side_fraction"] == pytest.approx(1)
    assert meters["bands_db"]["mud"] > -0.1
    assert meters["bands_db"]["presence"] < -70


def test_metrics_matches_full_measurement_for_dynamic_mono():
    sr = 48000
    samples = np.concatenate((0.16 * tone(sr, 1000, 2), 0.5 * tone(sr, 1000, 2.011)))
    report = intelligence.measure(samples, sr)
    meters = intelligence.metrics(samples, sr)
    assert meters["channels"] == 1
    assert meters["stereo_correlation"] is None
    assert meters["side_fraction"] == 0
    assert meters["bands_db"] == report["bands_db"]
    assert meters["dynamic_db"] == pytest.approx(20 * np.log10(0.5 / 0.16), abs=0.01)
    for key in ("lufs", "true_peak_db", "peak_db", "rms_db", "dynamic_db"):
        assert meters[key] == pytest.approx(report[key], abs=1e-5)


def test_metrics_estimates_inter_sample_peak():
    t = np.arange(4800)
    # At Fs/4, a quarter-cycle offset of pi/4 avoids sampling sine extrema.
    samples = 0.9 * np.sin(t * np.pi / 2 + np.pi / 4).astype(np.float32)
    meters = intelligence.metrics(samples, 48000)
    assert meters["true_peak_db"] > meters["peak_db"] + 2.5


@pytest.mark.parametrize("fn", [intelligence.measure, intelligence.metrics])
def test_cancel_and_invalid_samples(fn):
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        fn(np.zeros(800), SR, cancel)
    with pytest.raises(ValueError):
        fn(np.array([0.0, np.nan]), SR)
