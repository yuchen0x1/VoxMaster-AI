"""Post-fader insert chains and vocal-keyed accompaniment processing."""

import math
import numpy as np
from scipy import signal


INSERTS = {"presence": "存在感 EQ", "compress": "总线压缩", "width": "立体声宽度"}
INSERT_RANGES = {
    "presence": (-8.0, 8.0, 0.0),
    "compress": (0.0, 8.0, 0.0),
    "width": (0.0, 1.5, 1.0),
}


def default_rack():
    return {
        "order": list(INSERTS),
        "bypass": [],
        **{k: item[2] for k, item in INSERT_RANGES.items()},
    }


def default_routing():
    return dict(
        enabled=False,
        duck_db=0.0,
        mask_db=0.0,
        frequency=1800.0,
        threshold=-36.0,
        center=0.0,
    )


def validate_options(rack, routing=None):
    if sorted(rack["order"]) != sorted(INSERTS) or not set(rack["bypass"]) <= INSERTS.keys():
        raise ValueError("效果器顺序或旁通标识无效")

    def bounded(value, lo, hi):
        if not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError("混音效果参数超出范围")

    for key, (lo, hi, _) in INSERT_RANGES.items():
        bounded(rack[key], lo, hi)
    if routing is not None:
        if not isinstance(routing["enabled"], bool):
            raise ValueError("混音路由状态无效")
        for key, lo, hi in (
            ("duck_db", 0.0, 8.0),
            ("mask_db", 0.0, 8.0),
            ("frequency", 150.0, 6000.0),
            ("threshold", -80.0, -6.0),
            ("center", 0.0, 1.0),
        ):
            bounded(routing[key], lo, hi)


class LevelFollower:
    """5 ms stereo RMS detector with attack/release smoothing and sample ramps."""

    def __init__(self, sr):
        self.sr = sr
        self.previous = 0.0

    def curve(self, key, threshold, maximum, ratio, attack, release):
        hop = max(1, round(self.sr * 0.005))
        edges = np.arange(0, len(key), hop)
        lengths = np.minimum(hop, len(key) - edges)
        energy = np.add.reduceat(np.sum(np.square(key, dtype=np.float64), axis=1), edges) / (
            2 * lengths
        )
        db = 10 * np.log10(np.maximum(energy, 1e-12))
        wanted = np.clip((db - threshold) * (1 - 1 / ratio), 0.0, maximum)
        bounds = [self.previous]
        for target, count in zip(wanted, lengths):
            tau = attack if target > self.previous else release
            c = math.exp(-count / (self.sr * tau))
            self.previous = c * self.previous + (1 - c) * target
            bounds.append(self.previous)
        return np.interp(np.arange(1, len(key) + 1), np.r_[0, edges + lengths], bounds)


class InsertChain:
    def __init__(self, rack, sr):
        self.rack = rack
        self.follower = LevelFollower(sr)
        self.peak_filter = signal.iirpeak(min(2800.0, sr * 0.38), 1.0, fs=sr)
        self.zi = np.zeros((2, 2))

    def apply(self, chunk):
        for name in self.rack["order"]:
            val = self.rack[name]
            if name in self.rack["bypass"] or val == INSERT_RANGES[name][2]:
                continue
            if name == "presence":
                band, self.zi = signal.lfilter(*self.peak_filter, chunk, axis=0, zi=self.zi)
                chunk = chunk + (10 ** (val / 20) - 1) * band
            elif name == "compress":
                db = self.follower.curve(chunk, -20.0, val, 2.3, 0.018, 0.15)
                chunk = chunk * np.power(10.0, -db[:, None] / 20)
            else:
                mid = chunk.mean(axis=1, keepdims=True)
                chunk = mid + val * (chunk - mid)
        return chunk


class VocalKey:
    def __init__(self, params, sr):
        self.params = params
        self.follower = LevelFollower(sr)
        self.band = signal.iirpeak(min(params["frequency"], sr * 0.38), 1.15, fs=sr)
        self.zi = np.zeros((2, 2))

    def process(self, music, voice):
        settings = self.params
        maximum = max(settings["duck_db"], settings["mask_db"])
        if maximum == 0:
            return music
        if voice is None:
            voice = np.zeros_like(music)
        envelope = (
            self.follower.curve(voice, settings["threshold"], maximum, 3, 0.014, 0.19) / maximum
        )
        if settings["mask_db"]:
            band, self.zi = signal.lfilter(*self.band, music, axis=0, zi=self.zi)
            music = (
                music + (np.power(10.0, -envelope[:, None] * settings["mask_db"] / 20) - 1) * band
            )
        if settings["duck_db"]:
            music = music * np.power(10.0, -envelope[:, None] * settings["duck_db"] / 20)
        return music


def center_vocal(x, amount):
    if not amount:
        return x
    # Mid/Side narrowing without creating a new phase-inverted component.
    return (1 - amount) * x + amount * x.mean(axis=1, keepdims=True)
