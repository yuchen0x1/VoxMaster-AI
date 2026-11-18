"""Offline, version-isolated whole-file regression and excerpt generation for MC trials."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
import zipfile
from threading import Event
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads(
    Path(__file__).with_name("sources.json").read_text(encoding="utf-8")
)
BASELINE = "444455fd3e2cb5a5300131e277c29428a4eca39c4b297c55cdbaae0a35339844"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def dump(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def select_ranges(x, rate, source_id):
    """Choose before comparing versions, always from the decoded original."""
    seconds = len(x) / rate
    width = min(12, seconds)
    if seconds <= width + 1:
        return [{"start_frame": 0, "end_frame": len(x), "basis": "完整短样本"}]
    # Search a one-second grid for the strongest integrated PCM energy in the
    # first half; the later slice is fixed by elapsed time, independent of DSP.
    energy = np.array([np.mean(x[i : i + rate] ** 2) for i in range(0, len(x), rate)])
    rolling = np.convolve(energy, np.ones(12) / 12, mode="valid")
    cut = max(1, (len(energy) - 12) // 2)
    early = int(np.argmax(rolling[:cut]))
    spans = [(early, "前半段内 12 秒平均 PCM 能量最高")]
    if source_id.startswith("MC") and seconds >= 48:
        spans.append(
            (
                min(int(seconds) - 12, max(early + 12, round(0.71 * seconds))),
                "全曲时长 71% 附近",
            )
        )
    return [
        {
            "start_frame": start * rate,
            "end_frame": min(len(x), (start + 12) * rate),
            "basis": why,
        }
        for start, why in spans
    ]


def render(args):
    code_path = args.baseline_zip if args.version == "0.1.0" else args.snapshot
    if args.version == "0.1.0" and digest(code_path) != BASELINE:
        raise RuntimeError("0.1.0 source ZIP digest differs from the shipped version")
    if args.version == "0.1.1" and not code_path.exists():
        code_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            code_path, "x", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted((ROOT / "vox").glob("*.py")):
                archive.write(path, path.relative_to(ROOT))
    sys.path.insert(0, str(code_path.resolve()))
    from vox import audioio, service
    from vox import __version__

    if __version__ != args.version:
        raise RuntimeError(
            f"Requested {args.version}, imported {__version__} from {service.__file__}"
        )
    version_dir = args.output / "engineering" / args.version
    version_dir.mkdir(parents=True, exist_ok=True)
    dirs = {
        "local": args.local,
        "external": args.output / "external",
        "fixture": ROOT / "tests/fixtures",
    }
    for item in CATALOG:
        sid = item["id"]
        if args.only and sid not in args.only:
            continue
        path = dirs[item["location"]] / item["file"]
        if digest(path) != item["sha256"]:
            raise RuntimeError(f"Input digest mismatch: {sid}")
        dest = version_dir / sid
        if (dest / "report.json").is_file() and args.resume:
            continue
        dest.mkdir(exist_ok=True)
        cancel = Event()
        document = dict(
            source=str(path.resolve()),
            style=item["preset"],
            kind=item["kind"],
            history=[],
        )
        dry = service.prepare(document, cancel, lambda *_: None)
        if args.version == "0.1.0":
            from vox.interface import MainWindow

            # Run the released UI's own planning method with its two selected values.
            controls = SimpleNamespace(
                style=SimpleNamespace(currentText=lambda: item["preset"]),
                kind=SimpleNamespace(currentText=lambda: item["kind"]),
                custom={},
                s=dry,
            )
            params = MainWindow.current_params(controls)
        else:
            params = service.tuning_plan(
                dry.analysis, style=item["preset"], kind=item["kind"]
            )
        document.update(applied=True, params=params)
        wet = service.prepare(document, cancel, lambda *_: None, dry)
        assert wet.output.shape == dry.original.shape and np.isfinite(wet.output).all()
        selected = select_ranges(dry.original, service.SR, sid)
        for index, region in enumerate(selected, 1):
            token = sid + "-" + str(index)
            start, end = region["start_frame"], region["end_frame"]
            region["id"] = token
            if args.version == "0.1.0":
                audioio.encode(
                    dest / (token + "-original.wav"),
                    dry.original[start:end],
                    service.SR,
                    bitdepth=32,
                )
            audioio.encode(
                dest / (token + "-tuned.wav"),
                wet.output[start:end],
                service.SR,
                bitdepth=24,
            )
        assert digest(path) == item["sha256"]
        source_id = digest(code_path)
        report = dict(
            source=item,
            input_spec=dry.metadata,
            version=args.version,
            implementation=source_id,
            date=datetime.now().astimezone().isoformat(timespec="seconds"),
            processing_device="CPU / " + platform.platform(),
            listening_device=None,
            params=wet.document["params"],
            before=dry.analysis,
            after=wet.measured,
            clips=selected,
            execution=getattr(wet, "audit", None),
            warnings=getattr(wet, "warnings", None),
        )
        dump(dest / "report.json", report)
        print(
            args.version,
            sid,
            "frames",
            len(wet.output),
            "LUFS",
            round(wet.measured["lufs"], 2),
            flush=True,
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("version", choices=["0.1.0", "0.1.1"])
    p.add_argument("--local", required=True, type=Path)
    p.add_argument("--output", type=Path, default=ROOT / "build/acceptance-011")
    p.add_argument(
        "--baseline-zip",
        type=Path,
        default=ROOT / "build/acceptance-011/baseline-010-source.zip",
    )
    p.add_argument(
        "--snapshot",
        type=Path,
        default=ROOT / "build/acceptance-011/current-011-source.zip",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip previously completed cases for the same build",
    )
    p.add_argument("--only", nargs="+", choices=[item["id"] for item in CATALOG])
    render(p.parse_args())


if __name__ == "__main__":
    main()
