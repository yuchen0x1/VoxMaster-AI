"""Measure aligned, edited tracks. Recommendations are advisory until applied."""

import math

import numpy as np
from scipy import signal

from .analysis import k_weight
from .studio_effects import VocalKey
from .studio_session import BLOCK, TRACKS, checked


class StripMeter:
    def __init__(self, sr):
        self.sr = sr
        self.hop = round(0.1 * sr)
        self.sos = k_weight(sr)
        self.zi = np.zeros((2, 2, 2))
        self.carry = np.empty(0)
        self.energies = []
        self.cov = np.zeros(6)
        self.peak = 0.0

    def add(self, x):
        x = np.asarray(x, dtype="float64")
        y, self.zi = signal.sosfilt(self.sos, x, axis=0, zi=self.zi)
        energy = np.r_[self.carry, np.einsum("ij,ij->i", y, y)]
        used = len(energy) // self.hop * self.hop
        self.energies.extend(energy[:used].reshape(-1, self.hop).mean(axis=1))
        self.carry = energy[used:].copy()
        l, r = x.T
        self.cov += np.array(
            [
                len(l),
                l.sum(),
                r.sum(),
                np.einsum("i,i", l, l),
                np.einsum("i,i", r, r),
                np.einsum("i,i", r, l),
            ]
        )
        self.peak = max(self.peak, float(np.max(np.abs(x))))

    def result(self):
        powers = list(self.energies)
        if len(powers) < 4:
            powers.append(float(np.sum(self.carry)) / self.hop)
            powers += [0.0] * (4 - len(powers))
        blocks = np.convolve(powers, np.full(4, 0.25), "valid")
        absolute = blocks[blocks > 10 ** ((-70 + 0.691) / 10)]
        lufs = None
        if len(absolute):
            lufs = float(
                -0.691 + 10 * np.log10(absolute[absolute >= np.mean(absolute) * 0.1].mean())
            )
        n, sl, sr, ll, rr, lr = self.cov
        n = max(1, n)
        denominator = math.sqrt(max(0, ll - sl * sl / n) * max(0, rr - sr * sr / n))
        corr = (
            float(np.clip((lr - sl * sr / n) / denominator, -1, 1)) if denominator > 1e-12 else None
        )
        ratio = max(1e-12, (ll + rr + 2 * lr) / (2 * max(1e-20, ll + rr)))
        mono_db = float(10 * np.log10(ratio)) if ll + rr > 1e-15 else None
        return dict(
            lufs=lufs,
            correlation=corr,
            mono_db=mono_db,
            peak_db=float(20 * np.log10(max(1e-6, self.peak))),
        )


BAND_EDGES = (180, 450, 900, 1800, 3500, 6000)


def measure(session, cancel=None, master=None):
    """Measure rendered levels; estimate masking from simultaneously active, un-ducked stems."""
    names = [t for t in TRACKS if session.strip(t)["clips"]]
    if not names:
        raise ValueError("请先添加音轨")
    rate = session.sr
    streams = {t: session._strip_blocks(t, session.frames, cancel) for t in names}
    meters = {t: StripMeter(rate) for t in names}
    window = np.hanning(2048)
    hz = np.fft.rfftfreq(len(window), 1 / rate)
    bins = [(hz >= lo) & (hz < hi) for lo, hi in zip(BAND_EDGES, BAND_EDGES[1:])]
    levels = []
    spectra = []
    step = max(len(window), round(0.08 * rate), math.ceil(session.frames / 60000))
    routing = session.state["routing"]
    key = VocalKey(routing, rate) if routing["enabled"] else None
    for start in range(0, session.frames, BLOCK):
        checked(cancel)
        block = {t: next(s) for t, s in streams.items()}
        for name, x in block.items():
            if key is not None and name == "Instrumental":
                voice = None if session.strip("Vocal")["mute"] else block.get("Vocal")
                x = key.process(x, voice)
            meters[name].add(x)
        if "Vocal" not in block or "Instrumental" not in block:
            continue
        # Use exactly the same sample positions in both stems. An active phrase in
        # a different part of the song cannot generate a masking recommendation.
        for i in range(
            (-start) % step,
            len(block["Vocal"]) - len(window) + 1,
            step,
        ):
            pair = [block[t][i : i + len(window)] for t in ("Vocal", "Instrumental")]
            levels.append([10 * np.log10(max(1e-12, float(np.mean(x * x)))) for x in pair])
            power = [
                np.mean(np.abs(np.fft.rfft(x * window[:, None], axis=0)) ** 2, axis=1) for x in pair
            ]
            spectra.append([[float(p[b].sum() / max(1e-15, p.sum())) for b in bins] for p in power])
    measurements = {k: v.result() for k, v in meters.items()}
    master_meter = StripMeter(rate)
    if master is None:
        master = session.render(cancel)
    for start in range(0, len(master), BLOCK):
        checked(cancel)
        master_meter.add(master[start : start + BLOCK])
    measurements["Master"] = master_meter.result()
    recommendation = None
    if levels:
        levels = np.asarray(levels)
        spectra = np.asarray(spectra)
        floors = np.maximum(-65.0, np.percentile(levels, 90, axis=0) - 24)
        active = np.all(levels > floors, axis=1)
        if np.count_nonzero(active) >= 3:
            voice_db, music_db = np.median(levels[active], axis=0)
            shared = np.mean(np.minimum(spectra[active, 0], spectra[active, 1]), axis=0)
            idx = int(np.argmax(shared))
            freq = float(np.sqrt(BAND_EDGES[idx] * BAND_EDGES[idx + 1]))
            mask = float(np.clip(shared[idx], 0, 1))
            target = 2.0 + 2.0 * mask
            duck = float(np.clip(1 + (music_db - voice_db) * 0.22, 0, 4.0))
            audibility = float(np.clip((music_db - voice_db + 12.0) / 12.0, 0.0, 1.0))
            band_cut = float(np.clip(mask * audibility * 6.0, 0, 4.5))
            # Estimate attenuation already supplied by the keyed EQ and broadband
            # compressor at the median vocal level; avoid deducting this gain twice.
            relative_band = float(np.mean(spectra[active, 1, idx]))
            eq_credit = -10 * np.log10(max(1e-12, 1 - relative_band * (1 - 10 ** (-band_cut / 10))))
            delta = float(np.clip((voice_db - music_db) - target + duck + eq_credit, -12.0, 6.0))
            suggested = float(np.clip(session.strip("Instrumental")["gain"] + delta, -60, 12))
            base = measurements["Vocal"]
            # A strong antiphase signal would collapse under Mid/Side narrowing.
            safe_center = base["correlation"] is not None and base["correlation"] > 0
            center = 0.45 * (1 - base["correlation"]) if safe_center else 0.0
            recommendation = dict(
                music_gain=suggested,
                original_gain=session.strip("Instrumental")["gain"],
                vocal_db=float(voice_db),
                music_db=float(music_db),
                overlap_frames=int(np.sum(active)),
                band=[BAND_EDGES[idx], BAND_EDGES[idx + 1]],
                shared_fraction=mask,
                routing=dict(
                    enabled=True,
                    duck_db=duck,
                    mask_db=band_cut,
                    frequency=freq,
                    threshold=float(np.clip(voice_db - 9, -80, -6)),
                    center=float(center),
                ),
            )
    return dict(tracks=measurements, recommendation=recommendation)
