"""Windows continuous-render, export and multitrack transport stress test.

Run from source with: python scripts/soak.py OUTPUT.jsonl --minutes 20
The real output stream is muted so the loop can run unattended.
"""

import argparse
import ctypes
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from vox import audioio, engine
from vox.playback import Playback
from vox.studio_session import Session


class Memory(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_rss",
            "rss",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
            "private",
        )
    ]


def resources():
    counters = Memory()
    counters.cb = ctypes.sizeof(counters)
    handle = ctypes.c_void_p(-1)
    handles = wintypes.DWORD()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    if not ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(handles)):
        raise ctypes.WinError()
    return dict(
        rss_mib=round(counters.rss / 2**20, 1),
        private_mib=round(counters.private / 2**20, 1),
        handles=handles.value,
    )


def gpu():
    try:
        data = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            timeout=4,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        load, used = map(int, data.splitlines()[0].split(","))
        return dict(board_gpu_pct=load, board_vram_mib=used)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def run(log, seconds, device=None, application=False):
    here = Path(__file__).resolve().parents[1]
    recording = here / "tests/fixtures/fleurs-mandarin.wav"
    raw, _ = audioio.decode(recording)
    sr = audioio.WORK_RATE
    beat = (0.05 * np.sin(np.arange(len(raw)) * 2 * np.pi * 110 / sr)).astype("f4")
    accompaniment = np.repeat(beat[:, None], 2, axis=1)
    player = Playback()
    player.device = device
    player.volume = 0
    start = time.monotonic()
    baseline_cpu = time.process_time()
    last_report = start
    count = 0
    prev_pos = None
    source_hash = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (here / "vox").glob("*.py")
    }

    def write(event, **data):
        record = dict(
            time=datetime.now().astimezone().isoformat(timespec="seconds"),
            event=event,
            seconds=round(time.monotonic() - start, 3),
            cycles=count,
            **data,
        )
        log.write(json.dumps(record, ensure_ascii=False) + "\n")
        log.flush()

    with tempfile.TemporaryDirectory(prefix="vox-soak-") as tmp:
        folder = Path(tmp)
        if application:
            from vox.service import prepare, tuning_plan
            from vox.storage import project

            backing = folder / "backing.wav"
            audioio.encode(backing, accompaniment, sr, 32)
            doc = project(recording, "连续测试")
            doc["stems"]["Instrumental"] = str(backing)
            cancel = threading.Event()

            def progress(*args):
                pass

        write(
            "start",
            goal_seconds=seconds,
            output_device=device,
            application=application,
            source_seconds=len(raw) / sr,
            source_sha256=source_hash,
            **resources(),
            **gpu(),
        )
        try:
            player.play(
                Session({"Vocal": raw, "Instrumental": accompaniment}, sr).render(), sr, loop=True
            )
            while time.monotonic() - start < seconds:
                style = tuple(engine.PRESETS)[count % len(engine.PRESETS)]
                if application:
                    imported = prepare(doc, cancel, progress)
                    params = tuning_plan(imported.analysis, style)
                    updated = dict(doc, applied=True, params=params, style=style)
                    session = prepare(updated, cancel, progress, imported)
                    mix = session.output
                else:
                    before = engine.analyze(raw, sr)
                    params = engine.recommend(before, style)
                    rendered = engine.process(raw, sr, params)
                    mix = Session({"Vocal": rendered, "Instrumental": accompaniment}, sr).render()
                device_message = player.poll_device()
                if device_message:
                    write("transport", message=device_message, cursor=player.position)
                if not player.replace_buffer(mix):
                    raise RuntimeError(
                        f"Cannot replace transport, playing={player.playing}, rendered={mix.shape}, source={raw.shape}"
                    )
                path = folder / "result.wav"
                audioio.encode(path, mix, sr)
                exported, _ = audioio.decode(path)
                path.unlink()
                if exported.shape != raw.shape or not np.isfinite(exported).all():
                    raise ValueError("Invalid WAV round trip")
                count += 1
                now = time.monotonic()
                if now - last_report >= 15 or now - start >= seconds:
                    pos = player.position
                    if prev_pos == pos:
                        raise RuntimeError("Playback cursor stalled")
                    prev_pos = pos
                    write(
                        "sample",
                        playing=player.playing,
                        cursor_s=round(pos, 4),
                        underflows=player.underflows,
                        cpu_seconds=round(time.process_time() - baseline_cpu, 3),
                        scratch_bytes=sum(p.stat().st_size for p in folder.iterdir()),
                        **resources(),
                        **gpu(),
                    )
                    last_report = now
            write("complete", underflows=player.underflows)
        except BaseException as exc:
            write("failure", error=str(exc))
            raise
        finally:
            player.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--device", type=int)
    parser.add_argument("--application", action="store_true")
    args = parser.parse_args()
    if args.minutes <= 0:
        parser.error("minutes must be positive")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("x", encoding="utf-8") as dest:
        run(dest, args.minutes * 60, args.device, args.application)
