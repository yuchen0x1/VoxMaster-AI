"""Explicit diagnostic for the unpacked application and redistributed runtimes."""

import argparse
import json
from pathlib import Path
import tempfile
import traceback


def main(args):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("model_directory", nargs="?", type=Path)
    parser.add_argument("--recover-project", type=Path)
    parsed = parser.parse_args(args)
    report = parsed.report
    if report.exists():
        return 2
    evidence = {}
    try:
        from . import __version__

        evidence["version"] = __version__
        import av
        import numpy as np
        import onnxruntime
        import sounddevice
        from PySide6.QtWidgets import QApplication

        from .audioio import decode, encode
        from .engine import analyze, process, recommend
        from .visual import app_icon
        from .models_runtime import separate

        app = QApplication.instance() or QApplication([])
        assert not app_icon().isNull()
        evidence["qt_platform"] = app.platformName()
        evidence["portaudio"] = sounddevice.get_portaudio_version()
        from importlib.metadata import version
        evidence["runtimes"] = {pkg: version(pkg) for pkg in (
            "av", "numpy", "scipy", "sounddevice", "pyside6-essentials", "onnxruntime-directml"
        )}
        evidence["providers"] = onnxruntime.get_available_providers()
        evidence["ffmpeg"] = av.ffmpeg_version_info
        sr = 44100
        t = np.arange(sr * 2) / sr
        x = 0.18 * np.sin(2 * np.pi * 222 * t)
        audio = np.column_stack((x, x)).astype("float32")
        analysis = analyze(audio, sr)
        tuned = process(audio, sr, recommend(analysis))
        evidence["changed_rms"] = float(np.sqrt(np.mean((audio - tuned[: len(audio)]) ** 2)))
        assert evidence["changed_rms"] > 0.0001
        with tempfile.TemporaryDirectory() as folder:
            for ext in ["wav", "mp3", "flac", "aac"]:
                path = Path(folder) / ("render." + ext)
                encode(path, tuned, sr)
                decoded, meta = decode(path)
                assert len(decoded) >= len(tuned) - 2048 and np.isfinite(decoded).all()
                evidence[ext] = {"frames": len(decoded), "bytes": path.stat().st_size}
        if parsed.recover_project:
            from threading import Event
            from . import storage
            from .service import prepare

            document = storage.load_project(parsed.recover_project)
            restored = prepare(document, Event(), lambda fraction, message: None)
            preferences = storage.preferences()
            if Path(document["source"]).parent != Path(preferences["import_dir"]):
                raise ValueError("The stored import directory did not match the original recording")
            evidence["recovery"] = {
                "source": document["source"],
                "frames": len(restored.original),
                "import_dir": preferences["import_dir"],
                "style": document["style"],
            }
        if parsed.model_directory:
            messages = []
            voice, music = separate(
                audio,
                sr,
                root=parsed.model_directory,
                mode="DirectML",
                progress=lambda fraction, msg: messages.append(msg),
            )
            assert np.isfinite(voice).all() and np.isfinite(music).all()
            assert np.allclose(voice + music, audio, atol=1e-6)
            evidence["separation"] = messages[-1]
        evidence["status"] = "PASS"
    except Exception:
        evidence["status"] = "FAIL"
        evidence["error"] = traceback.format_exc()
    with report.open("x", encoding="utf-8") as output:
        json.dump(evidence, output, ensure_ascii=False, indent=2)
    return int(evidence["status"] != "PASS")
