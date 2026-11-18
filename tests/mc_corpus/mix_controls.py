"""Mix recorded stems at known RMS ratios. Both contributors are real CC0 recordings."""

import argparse
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vox.audioio import decode, encode


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def generate(folder):
    vocal = decode(folder / "FS738227.mp3")[0][44100 * 17 : 44100 * 29]
    for case, file, ratio_db in (
        ("RM01", "FS353853.mp3", 6.0),
        ("RM02", "FS360702.mp3", -9.0),
    ):
        stem = decode(folder / file)[0]
        # Loop the bed with a short fade at its endpoints, avoiding a splice click.
        ramp = np.linspace(0, 1, min(220, len(stem) // 2), dtype=np.float32)[:, None]
        stem[: len(ramp)] *= ramp
        stem[-len(ramp) :] *= ramp[::-1]
        bed = np.tile(stem, (1 + len(vocal) // len(stem), 1))[: len(vocal)]
        bed *= np.float32(rms(vocal) / max(1e-12, rms(bed)) * 10 ** (ratio_db / 20))
        mix = vocal + bed
        mix *= np.float32(0.75 / np.max(np.abs(mix)))
        path = folder / (case + ".wav")
        if not path.exists():
            encode(path, mix, 44100, bitdepth=32)
        print(case, "measured bed/vocal RMS dB", 20 * np.log10(rms(bed) / rms(vocal)))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    generate(p.parse_args().folder)
