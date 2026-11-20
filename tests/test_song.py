"""Song DSP contracts: measured adaptation, truthful evidence and safe handoffs."""

import json
from copy import deepcopy
from threading import Event

import numpy as np
import pytest

from vox import engine, song
from vox.analysis import loudness, true_peak
from vox.presets import PRESETS

SR = 16000
NUMERIC = {
    "vocal_gain_db": (-24, 12), "instrumental_gain_db": (-24, 12),
    "instrumental_low_db": (-6, 6), "instrumental_mid_db": (-6, 6),
    "instrumental_high_db": (-6, 6), "target_lufs": (-30, -9),
    "ceiling_db": (-6, -0.3),
}


def report(lufs=-22.0, peak=-5.0, dynamic=8.0, **bands):
    return dict(lufs=lufs, true_peak_db=peak, dynamic_db=dynamic,
                bands_db=dict(rumble=-22, body=-7, mud=-6, mid=-8,
                              presence=-12, sibilance=-18, air=-24) | bands)


def tone(hz=1000, seconds=0.8, amplitude=0.1, sr=SR, channels=2):
    x = amplitude * np.sin(2 * np.pi * hz * np.arange(round(seconds * sr)) / sr)
    return np.repeat(x[:, None], channels, axis=1).astype(np.float32)


def test_plan_is_canonical_independent_and_json_safe():
    source = {"target": song.TARGETS["clear"], "master": song.MASTERING["standard"],
              "vocal_gain_db": np.float32(1.25)}
    before = deepcopy(source)
    p = song.validate_plan(source)
    assert p["target"] == "clear" and p["master"] == "standard"
    assert set(p) == set(NUMERIC) | {"target", "master"}
    assert p["vocal_gain_db"] == 1.25
    assert p["instrumental_low_db"] == p["instrumental_gain_db"] == 0
    assert source == before
    assert song.validate_plan(p) == p
    json.dumps(p, allow_nan=False)
    assert set(song.TARGETS) == {"natural", "forward", "impact", "clear", "full", "custom"}
    assert set(song.MASTERING) == {"conservative", "standard", "strong", "custom"}
    assert all(any("\u4e00" <= char <= "\u9fff" for char in x)
               for x in list(song.TARGETS.values()) + list(song.MASTERING.values()))


@pytest.mark.parametrize("key", list(NUMERIC))
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True,
                                 np.bool_(False), "1", None, [], complex(1, 0)])
def test_plan_rejects_nonfinite_and_coercible_non_numeric_fields(key, bad):
    with pytest.raises(ValueError):
        song.validate_plan({key: bad})


@pytest.mark.parametrize("key,bounds", list(NUMERIC.items()))
def test_plan_strict_bounds_and_inclusive_endpoints(key, bounds):
    for value in bounds:
        assert song.validate_plan({key: value})[key] == value
    for value in (bounds[0] - 0.001, bounds[1] + 0.001):
        with pytest.raises(ValueError):
            song.validate_plan({key: value})


@pytest.mark.parametrize("bad", [None, [], "natural", {"unknown": 0},
                                 {"target": "wrong"}, {"master": "wrong"},
                                 {"target": []}, {"master": True}])
def test_plan_rejects_unknown_structure_and_choices(bad):
    with pytest.raises(ValueError):
        song.validate_plan(bad)


def test_recommend_adapts_balance_spectrum_dynamics_and_loudness():
    vocal, music, original = report(-24), report(-19), report(-18, -3, 7)
    before = deepcopy((vocal, music, original))
    natural = song.recommend(vocal, music, original)
    masked = song.recommend(report(-30, presence=-20), music, original)
    bright = song.recommend(vocal, report(-19, sibilance=-3), original)
    dynamic = song.recommend(vocal, music, report(-18, -3, 20))
    quiet = song.recommend(vocal, music, report(-27, -7, 10))
    forward = song.recommend(vocal, music, original, target="forward")
    assert masked["vocal_gain_db"] > natural["vocal_gain_db"]
    assert masked["instrumental_gain_db"] < natural["instrumental_gain_db"]
    assert masked["instrumental_mid_db"] < natural["instrumental_mid_db"]
    assert bright["instrumental_high_db"] < natural["instrumental_high_db"]
    assert dynamic["target_lufs"] < natural["target_lufs"]
    assert dynamic["ceiling_db"] < natural["ceiling_db"]
    assert quiet["target_lufs"] < natural["target_lufs"] - 5
    assert forward["vocal_gain_db"] > natural["vocal_gain_db"]
    assert (vocal, music, original) == before
    for result in (natural, masked, bright, dynamic, quiet, forward):
        assert song.validate_plan(result) == result
        json.dumps(result, allow_nan=False)


def test_recommend_targets_mastering_and_silence_are_bounded():
    v, i, o = report(-24), report(-20), report(-20, -6, 6)
    signatures = set()
    for target in song.TARGETS:
        for master in song.MASTERING:
            p = song.recommend(v, i, o, target, master)
            assert p["target"] == target and p["master"] == master
            signatures.add((p["vocal_gain_db"], p["instrumental_low_db"],
                            p["instrumental_mid_db"], p["instrumental_high_db"], p["target_lufs"]))
    assert len(signatures) >= 15
    plans = [song.recommend(v, i, o, master=m) for m in ("conservative", "standard", "strong")]
    assert plans[0]["target_lufs"] < plans[1]["target_lufs"] < plans[2]["target_lufs"]
    silent = report(-120, -120, 0)
    p = song.recommend(silent, silent, silent)
    assert p["vocal_gain_db"] == p["instrumental_gain_db"] == 0
    assert p["target_lufs"] == -30
    p = song.recommend(v, silent, o, target="full")
    assert p["instrumental_low_db"] == p["instrumental_mid_db"] == p["instrumental_high_db"] == 0
    assert p["vocal_gain_db"] == 0
    recovered = song.recommend(v, i, silent)
    assert recovered["target_lufs"] > -30
    hot = song.recommend(v, i, report(-8, 1, 3))
    assert hot["target_lufs"] <= -15 and hot["ceiling_db"] <= -1.5


@pytest.mark.parametrize("key,bad", [("lufs", float("nan")), ("true_peak_db", float("inf")),
                                    ("dynamic_db", -1), ("lufs", True), ("bands_db", None)])
def test_bad_measurements_fail_before_recommendation(key, bad):
    r = report()
    r[key] = bad
    with pytest.raises(ValueError):
        song.recommend(r, report(), report())
    with pytest.raises(ValueError):
        song.vocal_params(r)


def test_minimal_metrics_report_and_bad_band_validation():
    minimal = dict(lufs=-22, true_peak_db=-4, dynamic_db=8, bands_db={})
    assert song.recommend(minimal, minimal, minimal)
    assert song.vocal_params(minimal)
    r = report(body=float("nan"))
    with pytest.raises(ValueError):
        song.recommend(r, report(), report())


@pytest.mark.parametrize("style", list(PRESETS))
def test_vocal_params_disables_creative_effects_and_makeup_for_every_style(style):
    r = report(-26, -9, 12, sibilance=-7)
    before = deepcopy((r, PRESETS))
    p = song.vocal_params(r, style)
    assert {"denoise", "pitch", "space", "stereo", "saturate", "master"} <= set(p["disabled"])
    for key in ("makeup_db", "denoise", "drive", "pitch_strength", "semitones", "reverb", "delay"):
        assert p[key] == 0
    assert p["width"] == p["dry"] == 1
    assert 1 <= p["ratio"] <= 1.8 and 30 <= p["highpass_hz"] <= 70
    assert 0 <= p["deess"] <= 0.22
    assert max(abs(p[band + "_db"]) for band in ("body", "mud", "presence", "air")) <= 1.8
    assert p["tail_times"] == [] and "automation" not in p
    assert (r, PRESETS) == before
    assert engine.normalize(p) == p


def test_vocal_params_adapts_measured_level_dynamics_and_reference_without_wet_effects():
    low = song.vocal_params(report(-30, -14, 4))
    hot = song.vocal_params(report(-16, -2, 16))
    ref = song.vocal_params(report(-30, -14, 4), reference=report(presence=-3))
    assert low["threshold_db"] < hot["threshold_db"] - 10
    assert low["ratio"] < hot["ratio"]
    assert ref["presence_db"] > low["presence_db"]
    assert ref["makeup_db"] == ref["reverb"] == ref["pitch_strength"] == 0
    with pytest.raises(ValueError):
        song.vocal_params(report(), reference=report(-120))
    with pytest.raises(ValueError):
        song.vocal_params(report(), style="missing")
    x = tone(amplitude=0.04)
    p = song.vocal_params(report(-28, -20, 4))
    y = engine.process(x, SR, p)
    assert y.shape == x.shape and np.isfinite(y).all()
    assert np.sqrt(np.mean(y ** 2)) < np.sqrt(np.mean(x ** 2)) * 1.25


def test_stems_neutral_passthrough_identity_no_filter_and_no_full_copy(monkeypatch):
    v, i = tone(), tone(220, seconds=1.1)
    monkeypatch.setattr(engine, "filter_audio", lambda *args: pytest.fail("neutral plan filtered audio"))
    a, b = song.process_stems(v, i, SR, {})
    assert a is v and b is i
    mono = v[:, 0]
    a, _ = song.process_stems(mono, i, SR, {})
    assert a.shape == (len(mono), 1) and np.shares_memory(a, mono)


def test_stem_gain_preserves_lengths_channels_and_input_samples():
    v, i = tone(channels=1), tone(220, seconds=1.1)
    before = v.copy(), i.copy()
    a, b = song.process_stems(v, i, SR, dict(vocal_gain_db=6, instrumental_gain_db=-3))
    np.testing.assert_allclose(a, v * 10 ** (6 / 20), rtol=2e-7)
    np.testing.assert_allclose(b, i * 10 ** (-3 / 20), rtol=2e-7)
    assert a.shape == v.shape and b.shape == i.shape
    np.testing.assert_array_equal(v, before[0])
    np.testing.assert_array_equal(i, before[1])
    assert a.dtype == b.dtype == np.float32


@pytest.mark.parametrize("band,hz", [("low", 120), ("mid", 2200), ("high", 16000)])
def test_instrumental_eq_reuses_engine_filters_and_gain_on_owned_output(monkeypatch, band, hz):
    rate = 48000
    x = tone(hz, seconds=0.5, sr=rate)
    before = x.copy()
    filtered = []
    original_filter = engine.filter_audio

    def capture(*args):
        y = original_filter(*args)
        filtered.append(y)
        return y

    monkeypatch.setattr(engine, "filter_audio", capture)
    v, y = song.process_stems(x, x, rate,
                             {"instrumental_" + band + "_db": -4, "instrumental_gain_db": -1})
    assert v is x and y is filtered[0]
    ratio = np.std(y[rate // 10:]) / np.std(x[rate // 10:])
    assert ratio == pytest.approx(10 ** (-5 / 20), rel=0.035)
    np.testing.assert_array_equal(x, before)


def test_instrumental_eq_does_not_apply_vocal_highpass():
    x = np.full((SR, 2), 0.1, dtype=np.float32)
    _, y = song.process_stems(x, x, SR, {"instrumental_mid_db": -3})
    np.testing.assert_allclose(y[-1000:], x[-1000:], rtol=1e-5)


def test_master_silence_and_already_matching_material_are_true_passthrough():
    silence = np.zeros((SR, 2), dtype=np.float32)
    assert song.master_mix(silence, SR, {}) is silence
    x = tone()
    p = dict(target_lufs=loudness(x, SR), ceiling_db=-1.5)
    assert song.master_mix(x, SR, p) is x
    # Below the absolute gate, do not normalize noise into audibility.
    noise = tone(amplitude=1e-5)
    assert song.master_mix(noise, SR, {}) is noise


def test_conservative_master_changes_only_gain_and_limits_makeup():
    quiet = tone(amplitude=0.02)
    y = song.master_mix(quiet, SR, {"target_lufs": -10})
    np.testing.assert_allclose(y, quiet * 10 ** (2 / 20), atol=1e-8)
    impulse = np.zeros((SR, 2), dtype=np.float32)
    impulse[SR // 2] = 0.95
    y = song.master_mix(impulse, SR, {"target_lufs": -9})
    gain = y[SR // 2, 0] / impulse[SR // 2, 0]
    np.testing.assert_allclose(y, impulse * gain, atol=1e-7)
    assert true_peak(y, SR) <= 10 ** (-1.5 / 20) + 1e-6


@pytest.mark.parametrize("master", list(song.MASTERING))
def test_master_guards_clipping_intersample_peaks_tail_and_never_mutates_input(master):
    rate = 48000
    x = tone(11000, seconds=0.4, amplitude=1.3, sr=rate)
    x = np.vstack((x, np.zeros((37, 2), dtype=np.float32)))
    x[-3] = 1.8
    before = x.copy()
    y = song.master_mix(x, rate, dict(master=master, target_lufs=-9, ceiling_db=-2))
    assert y.shape == x.shape and y.dtype == np.float32
    assert np.isfinite(y).all() and np.max(np.abs(y)) < 1
    assert 20 * np.log10(true_peak(y, rate)) <= -2 + 0.002
    np.testing.assert_array_equal(x, before)


def test_master_adapts_limiter_budget_to_material_not_one_fixed_master(monkeypatch):
    calls = []
    actual_master = engine.master

    def capture(x, sr, p, cancel):
        calls.append(p.copy())
        return actual_master(x, sr, p, cancel)

    monkeypatch.setattr(engine, "master", capture)
    dense = tone(amplitude=0.25)
    dense[SR // 2] = 0.8
    transient = np.zeros_like(dense)
    transient[SR // 2] = 0.8
    p = dict(master="strong", target_lufs=-9)
    a = song.master_mix(dense, SR, p)
    assert len(calls) == 1
    b = song.master_mix(transient, SR, p)
    assert len(calls) == 1  # sparse transients are peak-scaled, not crushed
    transient_gain = b[SR // 2, 0] / transient[SR // 2, 0]
    np.testing.assert_allclose(b, transient * transient_gain, atol=1e-7)
    assert a.shape == b.shape
    assert calls[0]["target_lufs"] != p["target_lufs"]


def test_reconstruction_evidence_is_objective_even_for_a_bad_semantic_split():
    original = tone()
    # All music in one stem reconstructs perfectly but proves no separation.
    evidence = song.separation_evidence(original, original, np.zeros_like(original), SR)
    assert evidence["length_match"]
    assert evidence["reconstruction_error_db"] == -120
    assert evidence["reconstruction_rms_db"] == -120
    assert evidence["comparison_frames"] == len(original)
    assert not any("confidence" in key or "quality" in key for key in evidence)
    json.dumps(evidence, allow_nan=False)


def test_reconstruction_length_mismatch_counts_unmatched_tail_and_preserves_inputs():
    original = np.full((1000, 2), 0.1, dtype=np.float32)
    vocal = original[:500].copy()
    inst = np.zeros((1200, 1), dtype=np.float32)
    before = original.copy(), vocal.copy(), inst.copy()
    result = song.separation_evidence(original, vocal, inst, SR)
    assert result["comparison_frames"] == 1200 and result["overlap_frames"] == 500
    assert not result["length_match"] and result["warnings"]
    assert result["reconstruction_error_db"] == pytest.approx(10 * np.log10(0.5), abs=1e-5)
    for x, old in zip((original, vocal, inst), before):
        np.testing.assert_array_equal(x, old)
    silent = np.zeros_like(original)
    assert song.separation_evidence(silent, silent, silent, SR)["reconstruction_error_db"] == -120
    residual = song.separation_evidence(silent, original, silent, SR)
    assert residual["reconstruction_error_db"] is None
    assert np.isfinite(residual["reconstruction_rms_db"])


@pytest.mark.parametrize("operation", ["stems", "master", "evidence"])
def test_cancel_before_work(operation):
    cancel = Event()
    cancel.set()
    x = tone()
    with pytest.raises(InterruptedError):
        if operation == "stems":
            song.process_stems(x, x, SR, {}, cancel)
        elif operation == "master":
            song.master_mix(x, SR, {}, cancel)
        else:
            song.separation_evidence(x, x, x, SR, cancel)


@pytest.mark.parametrize("operation", ["stems", "master", "evidence"])
def test_mid_job_cancel_does_not_publish_partial_output_or_mutate_sources(operation):
    class CancelAfterChecks:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 7

    x = np.full((song._BLOCK * 3, 2), 0.05, dtype=np.float32)
    before = x.copy()
    cancel = CancelAfterChecks()
    with pytest.raises(InterruptedError):
        if operation == "stems":
            song.process_stems(x, x, SR, {"instrumental_low_db": -2}, cancel)
        elif operation == "master":
            song.master_mix(x, SR, {"master": "strong"}, cancel)
        else:
            song.separation_evidence(x, x, x, SR, cancel)
    np.testing.assert_array_equal(x, before)


def test_metrics_to_engine_stems_studio_and_master_preserves_instrumental_ending():
    from vox.intelligence import metrics
    from vox.studio_session import Session

    vocal, music = tone(700, amplitude=0.07), tone(180, seconds=1.15, amplitude=0.1)
    source_session = Session({"Vocal": vocal, "Instrumental": music}, SR)
    original = source_session.render()
    vr, ir, source = [metrics(x, SR) for x in (vocal, music, original)]
    plan = song.recommend(vr, ir, source, "clear", "standard")
    tuned = engine.process(vocal, SR, song.vocal_params(vr))
    a, b = song.process_stems(tuned, music, SR, plan)
    mixed = Session({"Vocal": a, "Instrumental": b}, SR).render()
    result = song.master_mix(mixed, SR, plan)
    assert result.shape == music.shape and len(a) == len(vocal)
    assert np.max(np.abs(result[len(vocal) + 10:])) > 0.001
    assert metrics(result, SR)["true_peak_db"] <= plan["ceiling_db"] + 0.01


def test_cancellation_after_eq_and_master_measurement_is_propagated(monkeypatch):
    x = tone()
    before = x.copy()
    cancel = Event()
    original_filter = engine.filter_audio

    def cancel_after_filter(*args):
        output = original_filter(*args)
        cancel.set()
        return output

    monkeypatch.setattr(engine, "filter_audio", cancel_after_filter)
    with pytest.raises(InterruptedError):
        song.process_stems(x, x, SR, {"instrumental_mid_db": -2}, cancel)
    cancel.clear()
    original_peak = song.true_peak

    def cancel_after_meter(*args):
        peak = original_peak(*args)
        cancel.set()
        return peak

    monkeypatch.setattr(song, "true_peak", cancel_after_meter)
    with pytest.raises(InterruptedError):
        song.master_mix(x, SR, {}, cancel)
    np.testing.assert_array_equal(x, before)


@pytest.mark.parametrize("bad_sr", [True, 7999, 192001, 16000.5, float("nan"), "16000"])
def test_bad_sample_rate_is_rejected(bad_sr):
    x = tone()
    with pytest.raises(ValueError):
        song.master_mix(x, bad_sr, {})


@pytest.mark.parametrize("bad", [np.empty((0, 2)), np.zeros((8, 3)), np.zeros((2, 2, 2)),
                                 np.full((8, 2), np.nan), np.full((8, 1), np.inf),
                                 np.ones((8, 2), dtype=complex)])
def test_invalid_audio_is_rejected_across_entrypoints(bad):
    x = tone()
    with pytest.raises(ValueError):
        song.process_stems(x, bad, SR, {})
    with pytest.raises(ValueError):
        song.master_mix(bad, SR, {})
    with pytest.raises(ValueError):
        song.separation_evidence(x, x, bad, SR)
