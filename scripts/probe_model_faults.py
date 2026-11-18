"""Run cancel and corruption checks against a temporary copy of the pinned weights."""

import argparse
import json
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from vox import audioio, engine, models_runtime, models_store


def run(weights):
    samples, _ = audioio.decode(
        Path(__file__).resolve().parents[1] / "tests/fixtures/fleurs-mandarin.wav"
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix="vox-faults-") as tmp:
        temp = Path(tmp)
        copy = temp / "weights"
        copy.mkdir()
        for name in models_store.FILES:
            shutil.copyfile(weights / name, copy / name)
        models_store.verify(copy)
        broken = copy / next(iter(models_store.FILES))
        with broken.open("r+b") as file:
            file.seek(-1, os.SEEK_END)
            final = file.read(1)
            file.seek(-1, os.SEEK_END)
            file.write(bytes([final[0] ^ 1]))
        try:
            models_store.verify(copy)
        except ValueError:
            results["equal_size_corruption"] = True
        shutil.copyfile(weights / broken.name, broken)
        models_store.verify(copy)
        results["restored_digest"] = True
        event = threading.Event()
        progress_log = []
        stop_at = None

        def progress(fraction, text):
            nonlocal stop_at
            progress_log.append(text)
            if 0 < fraction < 1:
                stop_at = time.monotonic()
                event.set()

        try:
            models_runtime.separate(
                np.tile(samples, (3, 1)), 44100, event, progress, root=copy, mode="DirectML"
            )
        except InterruptedError:
            if stop_at is None:
                raise
            results.update(
                gpu_cancel_seconds=round(time.monotonic() - stop_at, 3),
                provider=progress_log[-1],
                live_children=len(multiprocessing.active_children()),
            )
        # Confirm the model lock was released after cancelling the live process.
        with models_store.locked(copy):
            models_store.verify(copy)
        results["lock_released"] = True
    clip = np.tile(samples, (12, 1))
    params = engine.recommend(engine.analyze(samples, 44100))
    event = threading.Event()
    timer = threading.Timer(0.05, event.set)
    start = time.monotonic()
    timer.start()
    try:
        engine.process(clip, 44100, params, event)
    except InterruptedError:
        results["dsp_cancel_seconds"] = round(time.monotonic() - start, 3)
    finally:
        timer.cancel()
    results["status"] = (
        "PASS"
        if (
            results.get("equal_size_corruption")
            and results.get("live_children") == 0
            and results.get("provider", "").split(" · ")[0] == "DmlExecutionProvider"
            and 0 < results.get("dsp_cancel_seconds", 0) < 10
        )
        else "FAIL"
    )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("weights", type=Path)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    values = run(args.weights)
    with args.log.open("x", encoding="utf-8") as log:
        json.dump(
            dict(time=datetime.now().astimezone().isoformat(), **values),
            log,
            indent=2,
            ensure_ascii=False,
        )
    if values["status"] != "PASS":
        raise SystemExit(1)
