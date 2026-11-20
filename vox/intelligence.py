"""Audio reports and meters independent of project or UI state."""

from operator import index

import numpy as np
from scipy import signal

from . import engine
from .acoustics import extra_features
from .analysis import BANDS, FLOOR, as_audio, check, db, loudness, true_peak
from .quality import quality_metrics
from .reference import measure_role_space
from .segments import analyze_segments


def _input(samples, sr):
    try:
        sr = index(sr)
    except TypeError as exc:
        raise ValueError("Sample rate must be an integer number of Hz") from exc
    return as_audio(samples, sr), sr


def _routing(report):
    # Use observations, not the legacy source labels, level, or role buckets.
    # Even these observations are compatible with instruments as well as voices.
    evidence = []
    runs = report["acoustics"]["stable_pitch_runs"]
    if runs:
        evidence.append({"kind": "stable_pitch", "count": runs})
    disagreements = sum(part["dual_pitch"] for part in report["segments"])
    if disagreements:
        evidence.append(
            {"kind": "different_channel_periodicities", "count": disagreements}
        )
    return {
        "mode": "manual",
        "recommended": "unknown",
        "evidence": evidence,
        "reason": "acoustic_cues_not_role_specific" if evidence else "no_role_cues",
    }


def measure(samples, sr, cancel=None):
    """Return the service measurement stack at ``sr``, plus advisory ``routing``.

    The legacy ``classification``, segment types and ``role_space`` are kept
    for compatibility, not used to choose a route. Pitch and channel-periodicity
    cues do not identify a voice, accompaniment, or a mix; routing remains manual.
    ``cancel`` is an optional event-like object with an ``is_set()`` method.
    """
    check(cancel)
    x, sr = _input(samples, sr)
    report = engine.analyze(x, sr, cancel)
    report.update(extra_features(x, sr, report, cancel))
    report["segments"] = analyze_segments(x, sr, report, cancel)
    report.update(quality_metrics(x, sr, report, cancel))
    report["role_space"] = measure_role_space(x, sr, report, cancel)
    report["routing"] = _routing(report)
    check(cancel)
    return report


def inspect_file(report, metadata):
    """Return a shallow report copy annotated with its matching audioio metadata.

    ``source_metadata`` keeps audioio's source fields (including unknown bit
    depth as ``None``); its ``duration`` is the decoded duration. Existing report
    values describe the analyzed PCM, and are never adjusted to the source layout.
    ``inspection`` explains which estimates and inferences are warranted.
    """
    source = dict(metadata) if metadata is not None else {}
    channels = source.get("channels")
    if channels == 1:
        layout = "mono"
        stereo = "duplicated_mono" if report.get("channels") == 2 else "not_applicable"
    elif channels == 2:
        layout = "stereo"
        stereo = "decoded_pcm" if report.get("channels") == 2 else "unavailable"
    elif channels is not None and channels > 2:
        layout = "multichannel"
        stereo = "decoded_downmix" if report.get("channels") == 2 else "unavailable"
    else:
        layout = "unknown"
        stereo = "unavailable"

    lufs = report.get("lufs")
    level_status = (
        "unknown"
        if lufs is None
        else "below_loudness_gate"
        if lufs == FLOOR
        else "gated"
    )
    estimates = {
        key: note
        for key, note in {
            "true_peak_db": "4x oversampled estimate of reconstructed PCM peaks, in dBTP",
            "pitch_curve": "Periodic signal estimates, not verified vocal notes; 0 means no estimate",
            "key": "Tonal candidate, not a verified musical key",
            "bpm": "Onset periodicity candidate, not a verified tempo",
            "classification": "Legacy heuristic, not a verified source role",
        }.items()
        if report.get(key) is not None
    }
    acoustics = report.get("acoustics", {})
    for key, note in {
        "pulse_bpm": "Onset periodicity candidate, not a verified tempo",
        "decay20_s": "Observed envelope decline, not reverb time or a plugin setting",
        "repeat_delay_ms": "Repeated texture spacing, not proof of an echo effect",
    }.items():
        if acoustics.get(key) is not None:
            estimates[f"acoustics.{key}"] = note

    return dict(
        report,
        source_metadata=source,
        inspection={
            "measurement_basis": "decoded_pcm",
            "channel_layout": layout,
            "stereo_evidence": stereo,
            "level_status": level_status,
            "estimates": estimates,
            "unknown": {
                "source_role": "A waveform or channel layout does not identify the source role",
                "vocal_accompaniment_balance": "Requires separate stems; not measured from a mix",
                "effect_settings": "Envelope and repeat estimates do not recover effect settings",
            },
        },
    )


def metrics(samples, sr, cancel=None):
    """Return pitch-free song meters for mono or stereo PCM (8–192 kHz).

    ``sample_rate`` (Hz), ``channels`` and ``duration`` (seconds) describe the
    buffer. ``lufs`` is integrated gated K-weighted loudness (the -120 sentinel
    means no block passed the gate, not necessarily silence). ``true_peak_db``
    is the 4x oversampled peak estimate in dBTP; ``peak_db`` and ``rms_db`` are
    in dBFS. ``clipped_samples`` counts channel samples at/near full scale.
    ``bands_db`` gives Welch band powers relative to total analyzed band power
    (see ``analysis.BANDS``); no measured energy in a band uses -120 dB.
    ``dynamic_db`` is the 10th-to-90th percentile span of active 20 ms RMS
    frames, or 0 when no frame passes the gate. ``side_fraction`` is the share
    of mid+side energy in the side channel. ``stereo_correlation`` is Pearson
    L/R correlation, or None for mono or when either channel has no variance.
    No pitch, segment, or role analysis is run. Cancellation raises InterruptedError.
    """
    check(cancel)
    x, sr = _input(samples, sr)
    hop = round(sr * 0.02)
    channels = x.shape[1]
    band_energy = np.zeros(len(BANDS))
    levels = []
    channel_sum = np.zeros(channels)
    products = np.zeros((channels, channels))
    rms_sum = mid_e = side_e = peak = 0.0
    clipped = 0
    for start in range(0, len(x), hop * 160):
        check(cancel)
        block = x[start : start + hop * 160].astype(np.float64)
        if not np.isfinite(block).all():
            raise ValueError("录音包含非有限采样值")
        amplitude = np.abs(block)
        peak = max(peak, float(amplitude.max()))
        clipped += int(np.count_nonzero(amplitude >= 0.999969))
        squares = block * block
        rms_sum += squares.sum()
        frames = len(block) // hop
        if frames:
            levels.extend(
                db(np.sqrt(squares[: frames * hop].reshape(frames, -1).mean(axis=1)))
            )
        if len(block) % hop:
            levels.append(db(np.sqrt(squares[frames * hop :].mean())))
        if channels == 2:
            mid = (block[:, 0] + block[:, 1]) * 0.5
            side = (block[:, 0] - block[:, 1]) * 0.5
            mid_e += np.dot(mid, mid)
            side_e += np.dot(side, side)
            # Pearson correlation is offset-invariant; subtracting the first
            # frame also makes constant channels exactly zero-variance.
            shifted = block - x[0]
            channel_sum += shifted.sum(axis=0)
            products += shifted.T @ shifted
        # The same Welch window and weighting as analysis.analyze. Averaging
        # channel power rather than the waveform keeps opposite-phase energy.
        window = min(len(block), 2048)
        freqs, power = signal.welch(block, fs=sr, nperseg=window, axis=0)
        power = power.mean(axis=1)
        for j, (low, high) in enumerate(BANDS.values()):
            band_energy[j] += (
                power[(freqs >= low) & (freqs < high)].sum() * sr / window * len(block)
            )

    levels = np.asarray(levels)
    noise, strong = np.percentile(levels, [10, 95])
    threshold = min(strong - 12, max(strong - 28, noise + 9))
    active = levels[levels > max(-110, threshold)]
    normal = max(1e-20, band_energy.sum())
    correlation = None
    if channels == 2:
        covariance = products - np.outer(channel_sum, channel_sum) / len(x)
        scale = np.sqrt(max(0.0, covariance[0, 0]) * max(0.0, covariance[1, 1]))
        if scale > 1e-16:
            correlation = float(np.clip(covariance[0, 1] / scale, -1, 1))
    result = dict(
        sample_rate=sr,
        channels=channels,
        duration=len(x) / sr,
        lufs=loudness(x, sr, cancel),
        true_peak_db=float(db(true_peak(x, sr, cancel))),
        peak_db=float(db(peak)),
        rms_db=float(db(np.sqrt(rms_sum / x.size))),
        clipped_samples=clipped,
        bands_db={
            k: round(float(10 * np.log10(max(1e-12, e / normal))), 2)
            for k, e in zip(BANDS, band_energy)
        },
        dynamic_db=float(np.ptp(np.percentile(active, [10, 90])))
        if len(active)
        else 0.0,
        side_fraction=float(side_e / max(1e-12, mid_e + side_e)),
        stereo_correlation=correlation,
    )
    check(cancel)
    return result
