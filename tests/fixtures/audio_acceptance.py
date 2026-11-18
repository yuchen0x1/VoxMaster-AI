"""Generate reproducible audio scenarios and exercise the normal offline session service.

Example: .venv\Scripts\python tests/fixtures/audio_acceptance.py C:\temp\vox-qa-01
The destination must be new. Input recordings are opened read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import threading
import sys
from pathlib import Path

import av
import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vox.audioio import decode, encode
from vox.engine import analyze, recommend
from vox.service import SR, prepare

FIXTURE = Path(__file__).with_name("fleurs-mandarin.wav")
DIGEST = "a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b"


def signal_set():
    original, _ = decode(FIXTURE)
    level = np.max(np.abs(original))
    dry = original / level * 0.65
    t = np.arange(len(dry)) / SR
    rng = np.random.default_rng(894)
    noise = rng.normal(0, 0.012, dry.shape)
    noise += (0.009 * np.sin(2 * np.pi * 50 * t))[:, None]
    beat = np.mod(t, 0.5)
    kick = 0.18 * np.exp(-beat * 24) * np.sin(2 * np.pi * (48 * beat + 5 * (1 - np.exp(-beat * 18))))
    bass_note = np.choose(np.floor(t / 0.5).astype(int) % 4, [110.0, 146.832, 123.471, 98.0])
    bass = 0.10 * np.sin(2 * np.pi * np.cumsum(bass_note) / SR) * np.exp(-beat * 6)
    hat = signal.sosfilt(
        signal.butter(2, 6500, fs=SR, btype="highpass", output="sos"), rng.normal(0, 0.11, len(dry))
    )
    hat *= np.exp(-np.mod(t, 0.25) * 65)
    backing = np.column_stack((kick + bass + hat, kick + bass + np.roll(hat, 41)))
    # A 120 ms pressure burst near the loudest syllable stresses detector attack.
    strong = np.argmax(np.abs(dry[:, 0]))
    burst = 0.5 * np.exp(-(((np.arange(len(dry)) - strong) / (SR * 0.035)) ** 2))
    explosive = np.clip(dry + (burst * np.cos(2 * np.pi * 70 * t))[:, None], -0.99, 0.99)
    long_t = np.arange(SR) / SR
    sustain = 0.21 * np.sin(2 * np.pi * 165 * long_t) + 0.07 * np.sin(4 * np.pi * 165 * long_t)
    sustain *= np.minimum(1, long_t * 25) * np.minimum(1, (1 - long_t) * 3)
    tail = np.vstack((dry, np.column_stack((sustain, sustain)), np.zeros((SR // 2, 2))))
    yield "01-dry", dry
    yield "02-noisy", dry + noise
    yield "03-quiet", dry * 0.05
    yield "04-loud", np.clip(dry * 3.0, -1.0, 1.0)
    yield "05-plosive", explosive
    yield "06-sustained", tail
    yield "07-fast", signal.resample_poly(dry, 3, 4, axis=0)
    yield "08-backing", dry + backing
    yield "09-stereo-mix", dry * 0.35 + backing * 1.65
    yield "10-spoken", original


def file_digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def reference_meter(path: Path):
    """Run FFmpeg's r128 filter directly on decoder frames, independent of vox.analysis."""
    with av.open(str(path)) as media, tempfile.TemporaryDirectory() as folder:
        stream = media.streams.audio[0]
        graph = av.filter.Graph()
        source = graph.add_abuffer(
            sample_rate=stream.rate,
            format=stream.codec_context.format.name,
            layout=stream.layout.name,
            time_base=stream.time_base,
        )
        meter = graph.add("ebur128", "metadata=1:peak=true")
        log = Path(folder) / "r128.txt"
        metadata = graph.add("ametadata", mode="print", file=str(log))
        sink = graph.add("abuffersink")
        source.link_to(meter)
        meter.link_to(metadata)
        metadata.link_to(sink)
        graph.configure()

        def drain(output):
            while True:
                try:
                    output.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return

        for frame in media.decode(stream):
            source.push(frame)
            drain(sink)
        source.push(None)
        drain(sink)
        # Release the filter's file handle before reading its buffered metadata.
        del source, meter, metadata, sink, graph
        totals = dict(
            line.split("=", 1)
            for line in log.read_text().splitlines()
            if line.startswith("lavfi.r128.")
        )
        return float(totals["lavfi.r128.I"]), 20 * np.log10(
            max(1e-12, float(totals["lavfi.r128.true_peak"]))
        )


def exercise(path: Path, export: Path):
    before_hash = file_digest(path)
    cancel = threading.Event()
    document = {"source": str(path)}
    original = prepare(document, cancel, lambda *_: None)
    document.update(applied=True, params=recommend(original.analysis, "经典喊麦"))
    rendered = prepare(document, cancel, lambda *_: None, original)
    encode(export, rendered.output, SR, bitdepth=24)
    exported, meta = decode(export)
    measured = analyze(exported, SR)
    assert before_hash == file_digest(path)
    assert (
        meta["bit_depth"] == 24 and meta["channels"] == 2 and len(exported) == len(original.original)
    )
    assert np.isfinite(exported).all() and not np.allclose(exported, original.original)
    assert measured["true_peak_db"] < 0 and measured["clipped_samples"] == 0
    ref_lufs, ref_tp = reference_meter(export)
    # FFmpeg gate/oversampling implementations differ slightly. A 0.5 dB
    # divergence on interesting content needs an explicit investigation.
    assert abs(ref_lufs - measured["lufs"]) < 0.5 and abs(ref_tp - measured["true_peak_db"]) < 0.5
    return dict(
        case=path.name,
        seconds=round(measured["duration"], 3),
        input_lufs=round(original.analysis["lufs"], 3),
        output_lufs=round(measured["lufs"], 3),
        input_dbtp=round(original.analysis["true_peak_db"], 3),
        output_dbtp=round(measured["true_peak_db"], 3),
        ffmpeg_output_lufs=round(ref_lufs, 3),
        ffmpeg_output_dbtp=round(ref_tp, 3),
        clipped_output=measured["clipped_samples"],
        source_hash_preserved=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--recording", type=Path, help="Optional additional local recording")
    args = parser.parse_args()
    if file_digest(FIXTURE) != DIGEST:
        raise RuntimeError("The bundled recording differs from its published fixture hash")
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, audio in signal_set():
        path = args.output / (name + ".wav")
        encode(path, audio.astype(np.float32), SR, bitdepth=32)
        results.append(exercise(path, args.output / (name + "-master.wav")))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    if args.recording:
        results.append(exercise(args.recording, args.output / "local-recording-master.wav"))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    (args.output / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
