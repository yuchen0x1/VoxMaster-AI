"""Offline, version-isolated whole-file regression and excerpt generation for MC trials."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
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
_PRIVATE_ABSOLUTE = re.compile(r"(?i)^(?:[A-Z]:[\\/]|/|\\\\\\\\)")


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


def load_private_files(path):
    """Read an explicit local ID -> path mapping without reporting private values."""
    if path is None:
        return {}

    def unique_keys(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("--private-files must not contain duplicate keys.")
        return result

    try:
        values = json.loads(
            Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Cannot read --private-files: supply a UTF-8 JSON object.") from None
    if not isinstance(values, dict):
        raise ValueError("--private-files must be a JSON object mapping local IDs to paths.")
    local_ids = {item["id"] for item in CATALOG if item["location"] == "local"}
    for sid, value in values.items():
        if sid not in local_ids:
            raise ValueError("--private-files may contain only known local source IDs.")
        if (
            not isinstance(value, str)
            or not value.strip()
            or re.search(r"[\x00-\x1f\ud800-\udfff]", value)
        ):
            raise ValueError(f"--private-files entry {sid} must be a nonempty path string.")
        target = Path(value)
        if target.anchor and not target.is_absolute():
            raise ValueError(
                f"--private-files entry {sid} must be fully absolute or relative to --local."
            )
    return values


def load_private_digests(path):
    """Read an explicitly supplied, local-only ID -> SHA-256 mapping."""
    if path is None:
        return {}
    try:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Cannot read --private-digests: provide a UTF-8 JSON object "
            "mapping source IDs to their existing SHA-256 fingerprints."
        ) from exc
    if not isinstance(values, dict):
        raise ValueError("--private-digests must be a JSON object mapping IDs to SHA-256.")
    for sid, value in values.items():
        if not sid or not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise ValueError(
                f"--private-digests entry {sid!r} must contain exactly 64 hexadecimal "
                "SHA-256 characters; use the original fingerprint, not a new baseline."
            )
    return {sid: value.lower() for sid, value in values.items()}


def verify_source_digest(path, item, private_digests):
    """Always verify input bytes; never infer or persist a replacement baseline."""
    sid = item["id"]
    if item["location"] == "local":
        expected = private_digests.get(sid)
        if expected is None:
            raise ValueError(
                f"Local input {sid} requires --private-digests PATH with its original "
                "ID -> SHA-256 mapping (for example "
                ".audit/040-release-review/private-corpus-digests.json). "
                "No fingerprint baseline is generated automatically."
            )
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected) is None:
            raise ValueError(
                f"--private-digests entry {sid!r} must contain exactly 64 hexadecimal "
                "SHA-256 characters."
            )
        expected = expected.lower()
    else:
        expected = item["sha256"]
    try:
        actual = digest(path)
    except OSError:
        if item["location"] != "local":
            raise
        raise ValueError(f"Cannot read local input {sid}; check --local and --private-files.") from None
    if actual != expected:
        raise RuntimeError(f"Input digest mismatch: {sid}")


def without_source_path(metadata):
    return {key: value for key, value in metadata.items() if key != "path"}


def without_analysis_source_path(analysis):
    metadata = analysis.get("source_metadata")
    if isinstance(metadata, dict):
        return dict(analysis, source_metadata=without_source_path(metadata))
    return analysis


def _resume_report_is_public(path, item):
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if item["location"] != "local":
        return True
    if report.get("source") != item:
        return False

    def contains_private_path(value, key=None):
        if isinstance(value, dict):
            return any(
                contains_private_path(child, child_key)
                for child_key, child in value.items()
                if child_key != "source"
            )
        if isinstance(value, list):
            return any(contains_private_path(child, key) for child in value)
        if not isinstance(value, str):
            return False
        return key in {"path", "file", "filename"} or _PRIVATE_ABSOLUTE.search(value) is not None

    return not contains_private_path(report)


def render(args):
    private_digests = load_private_digests(args.private_digests)
    private_files = load_private_files(args.private_files)
    dirs = {
        "local": args.local,
        "external": args.output / "external",
        "fixture": ROOT / "tests/fixtures",
    }
    items = [item for item in CATALOG if not args.only or item["id"] in args.only]
    # Resolve once and verify before creating any output, including on resume.
    sources = []
    for item in items:
        sid, location = item["id"], item["location"]
        filename = item["file"]
        if location == "local":
            filename = private_files.get(sid, filename)
        try:
            path = (dirs[location] / filename).resolve()
        except (OSError, RuntimeError):
            if location != "local":
                raise
            raise ValueError(f"Cannot resolve local input {sid}; check --local and --private-files.") from None
        verify_source_digest(path, item, private_digests)
        sources.append((item, path))
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
    for item, path in sources:
        sid = item["id"]
        dest = version_dir / sid
        existing_report = dest / "report.json"
        if existing_report.is_file() and args.resume:
            if not _resume_report_is_public(existing_report, item):
                raise ValueError(
                    f"--resume refuses a report with a private source path: {sid}"
                )
            continue
        dest.mkdir(exist_ok=True)
        cancel = Event()
        document = dict(
            source=str(path),
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
        verify_source_digest(path, item, private_digests)
        source_id = digest(code_path)
        input_spec, before, after = dry.metadata, dry.analysis, wet.measured
        if item["location"] == "local":
            input_spec = without_source_path(input_spec)
            before = without_analysis_source_path(before)
            after = without_analysis_source_path(after)
        report = dict(
            source=item,
            input_spec=input_spec,
            version=args.version,
            implementation=source_id,
            date=datetime.now().astimezone().isoformat(timespec="seconds"),
            processing_device="CPU / " + platform.platform(),
            listening_device=None,
            params=wet.document["params"],
            before=before,
            after=after,
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
    p.add_argument(
        "--private-files",
        type=Path,
        help="Local-only JSON mapping of IDs to absolute paths or paths relative to --local",
    )
    p.add_argument(
        "--private-digests",
        type=Path,
        help="Local-only JSON mapping of source IDs to existing SHA-256 fingerprints",
    )
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
    try:
        render(p.parse_args())
    except ValueError as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
