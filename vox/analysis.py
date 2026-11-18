"""Local measurements. All times in seconds; amplitudes reference float full scale."""

import math
import numpy as np
from scipy import signal, fft

FLOOR = -120.0
BANDS = {
    "rumble": (20, 80),
    "body": (80, 220),
    "mud": (220, 550),
    "mid": (550, 1800),
    "presence": (1800, 4800),
    "sibilance": (4800, 9000),
    "air": (9000, 20000),
}
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def check(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("任务已取消")


def as_audio(audio, sr):
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if not (8000 <= sr <= 192000 and x.ndim == 2 and len(x) and x.shape[1] in (1, 2)):
        raise ValueError("需要 8–192 kHz 单声道或立体声音频")
    return x


def db(value):
    return 20 * np.log10(np.maximum(value, 1e-6))


def k_weight(sr):
    # Bilinear K-weighting coefficients, ITU-R BS.1770 for mono/stereo.
    k = np.tan(np.pi * 1681.974450955533 / sr)
    vh = 10 ** (3.999843853973347 / 20)
    q = 0.7071752369554196
    shelf_b = np.array(
        [
            vh + vh**0.499666774155 * k / q + k * k,
            2 * (k * k - vh),
            vh - vh**0.499666774155 * k / q + k * k,
        ]
    )
    shelf_a = np.array([1 + k / q + k * k, 2 * (k * k - 1), 1 - k / q + k * k])
    k = np.tan(np.pi * 38.13547087602444 / sr)
    q = 0.5003270373238773
    hp_a = np.array([1 + k / q + k * k, 2 * (k * k - 1), 1 - k / q + k * k])
    return np.array([np.r_[shelf_b, shelf_a] / shelf_a[0], np.r_[[1, -2, 1], hp_a / hp_a[0]]])


def loudness(x, sr, cancel=None):
    hop = round(0.1 * sr)
    sos = k_weight(sr)
    zi = np.zeros((2, 2, x.shape[1]))
    powers = []
    for i in range(0, len(x), 100 * hop):
        check(cancel)
        y, zi = signal.sosfilt(sos, x[i : i + 100 * hop], axis=0, zi=zi)
        energy = np.sum(y * y, axis=1)
        n = len(energy) // hop
        if n:
            powers.extend(energy[: n * hop].reshape(n, hop).mean(axis=1))
        if len(x) < 4 * hop and len(energy) % hop:
            powers.append(np.sum(energy[n * hop :]) / hop)
    if len(powers) < 4:
        powers = list(powers) + [0.0] * (4 - len(powers))
    blocks = np.convolve(powers, [0.25] * 4, mode="valid")

    def level(power):
        return max(FLOOR, -0.691 + 10 * math.log10(max(1e-20, power)))

    above = blocks[blocks > 10 ** ((-70 + 0.691) / 10)]
    if len(above) == 0:
        return FLOOR
    gated = above[above >= np.mean(above) * 0.1]
    return float(level(np.mean(gated)))


def true_peak(x, sr, cancel=None):
    peak = 0.0
    # Sample on both sides of each boundary so the reconstruction filter sees no artificial edges.
    for start in range(0, len(x), sr * 2):
        check(cancel)
        end = min(len(x), start + sr * 2)
        left, right = max(0, start - 32), min(len(x), end + 32)
        over = signal.resample_poly(x[left:right], 4, 1, axis=0)
        peak = max(peak, float(np.max(np.abs(over[(start - left) * 4 : (end - left) * 4]))))
    return peak


def pitch_track(x, sr, cancel=None, *, return_confidence=False):
    # Decimation includes an anti-aliasing filter. Normalized autocorrelation avoids
    # a bias toward long periods; restrict correction to confident periodic frames.
    dec = max(1, round(sr / 8000))
    hop = max(1, round(0.02 * sr / dec))
    rate = sr / dec
    width = round(0.05 * rate)
    lo, hi = max(2, int(rate / 650)), int(rate / 65)
    leads, tones, confidence = [], [], []
    for start in range(0, len(x), hop * dec * 300):
        check(cancel)
        end = min(len(x), start + hop * dec * 300 + width * dec)
        mono = x[start:end].mean(axis=1)
        y = signal.resample_poly(mono, 1, dec)
        if len(y) < width:
            continue
        f = np.lib.stride_tricks.sliding_window_view(y, width)[::hop][:300].copy()
        f -= f.mean(axis=1, keepdims=True)
        spatial = np.zeros(len(f))
        if x.shape[1] == 2:
            side = (x[start:end, 0]-x[start:end, 1])*.5
            if np.any(side):
                side = signal.resample_poly(side, 1, dec)
                side_frames = np.lib.stride_tricks.sliding_window_view(side, width)[::hop][:len(f)]
                side_energy = np.mean(side_frames**2, axis=1)
                spatial = side_energy/(side_energy+np.mean(f*f, axis=1)+1e-15)
        ac = fft.irfft(np.abs(fft.rfft(f, n=2 * width, axis=1)) ** 2, n=2 * width, axis=1)[
            :, : hi + 2
        ]
        energies = np.pad(np.cumsum(f * f, axis=1), ((0, 0), (1, 0)))
        lags = np.arange(hi + 2)
        den = np.sqrt(
            np.maximum(1e-16, energies[:, width - lags] * (energies[:, -1:] - energies[:, lags]))
        )
        corr = np.clip(ac / den, -1.0, 1.0)
        for j, row in enumerate(corr):
            peaks = (
                np.where(
                    (row[lo : hi + 1] >= row[lo - 1 : hi]) & (row[lo : hi + 1] > row[lo + 1 : hi + 2])
                )[0]
                + lo
            )
            hz = 0.0
            certainty = 0.0
            if len(peaks) and energies[j, -1] / width > 1e-8:
                valid = peaks[row[peaks] >= max(0.78, 0.94 * np.max(row[peaks]))]
                if len(valid):
                    lag = valid[0]
                    a, b, c = row[lag - 1 : lag + 2]
                    shift = 0.5 * (c - a) / max(1e-6, 2 * b - a - c)
                    hz = float(rate / (lag + np.clip(shift, -0.5, 0.5)))
                    certainty = float(row[lag] * (1-.45*spatial[j]))
                    if certainty < .72:
                        hz, certainty = 0., 0.
            leads.append(float(start / sr + (j * hop + width / 2) / rate))
            tones.append(hz)
            confidence.append(certainty)
    tones, confidence = np.asarray(tones), np.asarray(confidence)
    if len(tones) >= 3:
        midi = 12*np.log2(np.maximum(1., tones))
        # Correct isolated low-confidence octave jumps only when the frames
        # on both sides agree. Sustained register transitions remain intact.
        glitches = ((tones[:-2]>0) & (tones[1:-1]>0) & (tones[2:]>0) &
                    (np.abs(midi[2:]-midi[:-2])<.6) &
                    (np.abs(np.abs(midi[1:-1]-midi[:-2])-12)<.65) & (confidence[1:-1]<.94))
        k = np.flatnonzero(glitches)+1
        tones[k] = np.sqrt(tones[k-1]*tones[k+1])
    if return_confidence:
        return np.asarray(leads), tones, confidence
    return np.asarray(leads), tones


def musical_key(hz):
    midi = 69 + 12 * np.log2(hz / 440) if len(hz) else np.array([])
    if len(midi) < 24:
        return None, None
    hist = np.bincount(np.rint(midi).astype(int) % 12, minlength=12)
    if (hist > 0.035 * hist.sum()).sum() < 4:
        return None, None
    profiles = {
        "Major": [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        "Minor": [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    }
    scores = sorted(
        [
            (np.corrcoef(hist, np.roll(profile, i))[0, 1], NOTES[i], mode)
            for mode, profile in profiles.items()
            for i in range(12)
        ],
        reverse=True,
    )
    if scores[0][0] > 0.55 and scores[0][0] - scores[1][0] > 0.07:
        return scores[0][1:]
    return None, None


def mains_hum(x, sr, cancel):
    if len(x) < sr * 2:
        return None
    # Sample quiet one-second windows across the file. A recurring narrow line
    # must dominate adjacent bins in most sampled windows to suggest a notch.
    starts = np.linspace(0, len(x) - sr, min(24, len(x) // sr), dtype=int)
    energies = np.array([np.mean(x[i : i + sr] ** 2) for i in starts])
    starts = starts[np.argsort(energies)[: max(2, len(starts) // 3)]]
    scores = {50: [], 60: []}
    window = signal.windows.hann(sr, sym=False)
    for start in starts:
        check(cancel)
        spec = np.abs(np.fft.rfft(x[start : start + sr].mean(axis=1) * window)) * 4 / sr
        for hz in scores:
            line = max(spec[hz - 1 : hz + 2])
            base = np.median(np.r_[spec[hz - 8 : hz - 2], spec[hz + 3 : hz + 9]])
            scores[hz].append(line > 0.001 and line > 8 * max(base, 1e-8))
    for hz, hits in scores.items():
        if np.mean(hits) >= 0.8:
            return hz
    return None


def late_energy(x, sr, tails):
    values = []
    for tail in tails:
        cut = round(tail * sr)
        end = cut + round(0.13 * sr)
        if cut < 0.1 * sr or end > len(x):
            continue
        onset = x[cut - round(0.10 * sr) : cut]
        late = x[cut + round(0.045 * sr) : end]
        energy = np.mean(onset * onset)
        if energy > 1e-9:
            values.append(10 * np.log10(max(1e-12, np.mean(late * late)) / energy))
    return round(float(np.median(values)), 2) if values else None


def analyze(audio, sr, cancel=None):
    x = as_audio(audio, sr)
    hop = max(1, round(sr * 0.02))
    levels, band_energy = [], np.zeros(len(BANDS))
    rms_sum = mid_e = side_e = 0.0
    peak, clipped = 0.0, 0
    for start in range(0, len(x), hop * 160):
        check(cancel)
        chunk = x[start : start + hop * 160]
        if not np.isfinite(chunk).all():
            raise ValueError("录音包含非有限采样值")
        rms_sum += np.sum(chunk**2, dtype=np.float64)
        peak = max(peak, float(np.max(np.abs(chunk))))
        clipped += int(np.count_nonzero(np.abs(chunk) >= 0.999969))
        mid = (chunk[:, 0] + chunk[:, -1]) * 0.5
        side = (chunk[:, 0] - chunk[:, -1]) * 0.5
        mid_e += np.dot(mid, mid)
        side_e += np.dot(side, side)
        for i in range(0, len(chunk), hop):
            levels.append(float(np.sqrt(np.mean(chunk[i : i + hop] ** 2))))
        # Integrate stereo spectral power without cancelling opposite-phase material.
        window = min(len(chunk), 2048)
        freqs, power = signal.welch(chunk, fs=sr, nperseg=window, axis=0)
        power = power.mean(axis=1)
        for j, (low, high) in enumerate(BANDS.values()):
            band_energy[j] += power[(freqs >= low) & (freqs < high)].sum() * sr / window * len(chunk)
    levels = np.asarray(levels)
    level_db = db(levels)
    noise, typical, strong = np.percentile(level_db, [10, 60, 95])
    # Relative gates remain stable when an otherwise identical recording is
    # imported with a different microphone gain.
    threshold = min(strong - 12, max(strong - 28, noise + 9))
    active = level_db > max(-110, threshold)
    active_levels = level_db[active]
    dyn = float(np.ptp(np.percentile(active_levels, [10, 90]))) if len(active_levels) else 0.0
    normal = max(1e-20, sum(band_energy))
    bands = {
        k: round(float(10 * np.log10(max(1e-12, e / normal))), 2) for k, e in zip(BANDS, band_energy)
    }
    times, hz, confidence = pitch_track(x, sr, cancel, return_confidence=True)
    from .tail011 import phrase_boundaries

    phrases = phrase_boundaries(level_db, hop / sr, len(x) / sr, times, hz)
    tails = [item["end"] for item in phrases if item["candidate"]]
    voiced = hz[hz > 0]
    key, scale = musical_key(voiced)
    detuning = None
    if len(voiced):
        notes = 69 + 12 * np.log2(voiced / 440)
        detuning = round(float(100 * np.median(abs(notes - np.rint(notes)))), 1)
    decay_db = late_energy(x, sr, tails)
    hum = mains_hum(x, sr, cancel)
    bursts = int(
        np.count_nonzero((np.diff(level_db, prepend=level_db[0]) > 16) & (level_db > strong - 3))
    )
    # Autocorrelate positive level changes. Suppress BPM on speech with no recurring pulse.
    onset = np.maximum(0, np.diff(np.clip(level_db, -70, 0), prepend=level_db[0]))
    bpm = None
    if len(onset) > 150 and np.std(onset) > 0.15:
        onset -= onset.mean()
        corr = signal.correlate(onset, onset, method="fft", mode="full")[len(onset) - 1 :]
        lag = int(np.argmax(corr[16:50])) + 16
        if corr[lag] > max(1e-8, 0.28 * corr[0]):
            bpm = round(60 * sr / (lag * hop), 1)
    ratio = float(side_e / max(1e-12, mid_e + side_e))
    cls = "其他 / 不确定"
    fraction = float(len(voiced) / max(1, active.sum()))
    if ratio > 0.18 and len(voiced) > 12:
        cls = "疑似人声与伴奏混合"
    elif fraction > 0.7 and key:
        cls = "疑似旋律型人声"
    elif fraction > 0.22 and ratio < 0.1 and dyn > 2:
        cls = "疑似语音喊麦"
    lufs = loudness(x, sr, cancel)
    tp = float(db(true_peak(x, sr, cancel)))
    issues = [f"综合响度 {lufs:.1f} LUFS，4 倍过采样真峰值 {tp:.1f} dBTP。"]
    if clipped:
        issues.append(f"{clipped} 个声道采样接近或超过满刻度，原录音可能已有削波。")
    if bands["mud"] > -4:
        issues.append(
            f"220–550 Hz 占分析频带能量的 {100 * 10 ** (bands['mud'] / 10):.0f}%，可尝试削减浑浊感。"
        )
    if bands["sibilance"] > -9:
        issues.append(f"4.8–9 kHz 相对能量 {bands['sibilance']:.1f} dB，建议试听齿音。")
    if dyn > 12:
        issues.append(f"活动帧电平的 10–90 百分位相差 {dyn:.1f} dB，建议适量压缩。")
    if len(tails):
        issues.append(f"检测到 {len(tails)} 个持续发声后进入停顿的位置，可编辑尾音发送。")
    if ratio > 0.5:
        issues.append(f"侧声道能量占 {ratio:.0%}，合并为单声道时可能丢失较多内容。")
    if hum:
        issues.append(f"较安静的分析窗口里反复测到 {hum} Hz 窄带峰，建议试听电源嗡声抑制。")
    if bursts:
        issues.append(f"{bursts} 个 20 ms 帧在强声段出现超过 16 dB 的突增，请检查爆发音。")
    if decay_db is not None:
        issues.append(f"停顿后 45–130 ms 的能量相对句尾为 {decay_db:.1f} dB，可用作空间参考。")
    return dict(
        duration=len(x) / sr,
        sample_rate=sr,
        channels=x.shape[1],
        peak_db=float(db(peak)),
        true_peak_db=tp,
        lufs=lufs,
        rms_db=float(db(np.sqrt(rms_sum / x.size))),
        dynamic_db=dyn,
        noise_db=float(noise),
        active_db=float(np.median(active_levels)) if len(active_levels) else FLOOR,
        active_fraction=float(active.mean()),
        clipped_samples=clipped,
        bands_db=bands,
        side_fraction=ratio,
        pitch_curve=[[round(t, 4), round(f, 2)] for t, f in zip(times, hz)],
        pitch_confidence=np.round(confidence, 3).tolist(),
        tail_candidates=phrases,
        key=key,
        scale=scale,
        bpm=bpm,
        tail_times=tails,
        classification=cls,
        diagnostics=issues,
        late_energy_db=decay_db,
        hum_hz=hum,
        burst_count=bursts,
        pitch_deviation_cents=detuning,
    )
