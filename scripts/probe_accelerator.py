"""Verify an actual provider on both Spleeter graphs and compare the stems to CPU."""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import onnxruntime as ort

from vox import audioio, models_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["DirectML", "CUDA"])
    parser.add_argument("weights", type=Path)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    expected = {"CUDA": "CUDAExecutionProvider", "DirectML": "DmlExecutionProvider"}[args.mode]
    pcm, _ = audioio.decode(
        Path(__file__).resolve().parents[1] / "tests/fixtures/fleurs-mandarin.wav"
    )
    voice = pcm[: 8 * 44100] * (0.12 / np.sqrt(np.mean(pcm[: 8 * 44100] ** 2)))
    t = np.arange(len(voice)) / 44100
    beat = (0.115 * np.sin(2 * np.pi * 110 * t) + 0.08 * np.sin(2 * np.pi * 165 * t)) * (
        0.35 + 0.65 * np.exp(-4 * (t % 0.5))
    )
    source = voice + np.column_stack((beat, 0.8 * beat)).astype("f")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("x", encoding="utf-8") as out:

        def write(**values):
            out.write(
                json.dumps(
                    dict(time=datetime.now().astimezone().isoformat(), **values), ensure_ascii=False
                )
                + "\n"
            )
            out.flush()

        write(runtime=ort.__version__, requested=args.mode, available=ort.get_available_providers())
        if expected not in ort.get_available_providers():
            raise RuntimeError(f"{expected} unavailable")
        baseline, _ = models_runtime.separate(source, 44100, root=args.weights, mode="CPU")
        events = []

        def progress(fraction, message):
            write(fraction=fraction, message=message)
            events.append(message)

        start = time.perf_counter()
        vocal, backing = models_runtime.separate(
            source, 44100, root=args.weights, mode=args.mode, progress=progress
        )
        delta = float(np.max(abs(vocal - baseline)))
        error = float(np.max(abs(vocal + backing - source)))
        sdr_gain = float(
            10 * np.log10(np.sum((source - voice) ** 2) / np.sum((vocal - voice) ** 2))
        )
        ok = (
            events[-1].split(" · ")[0] == expected
            and delta < 0.002
            and error < 1e-6
            and sdr_gain > 3
        )
        write(
            status="PASS" if ok else "FAIL",
            frames=len(vocal),
            elapsed=round(time.perf_counter() - start, 3),
            max_cpu_delta=delta,
            max_reconstruction_error=error,
            sdr_gain_db=sdr_gain,
        )
        if not ok:
            raise RuntimeError("Actual provider or numerical checks failed; see log")


if __name__ == "__main__":
    main()
