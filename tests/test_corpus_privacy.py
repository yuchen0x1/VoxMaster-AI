import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

SCRIPT = Path(__file__).with_name("mc_corpus") / "render_trials.py"
SPEC = importlib.util.spec_from_file_location("corpus_render_trials", SCRIPT)
render_trials = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_trials)
LOCAL = next(item for item in render_trials.CATALOG if item["location"] == "local")


def test_catalog_local_filenames_are_neutral():
    local = [item for item in render_trials.CATALOG if item["location"] == "local"]
    assert sorted(item["id"] for item in local) == [f"MC{i:02}" for i in range(1, 6)]
    for item in local:
        # Deliberately avoid pytest's assertion introspection on private fields.
        if item["file"] != item["id"] + ".mp3":
            pytest.fail(f'{item["id"]} must use a neutral catalog filename', pytrace=False)
        if item.get("private_digest_required") is not True or "sha256" in item:
            pytest.fail(f'{item["id"]} must use only a private digest', pytrace=False)


def test_private_mapping_verifies_input_bytes(tmp_path):
    source = tmp_path / "synthetic-input.bin"
    raw = b"synthetic corpus input"
    source.write_bytes(raw)
    mapping = tmp_path / "private-digests.json"
    mapping.write_text(
        json.dumps({LOCAL["id"]: hashlib.sha256(raw).hexdigest().upper()}),
        encoding="utf-8",
    )
    digests = render_trials.load_private_digests(mapping)
    render_trials.verify_source_digest(source, LOCAL, digests)
    source.write_bytes(b"modified input")
    with pytest.raises(RuntimeError, match="Input digest mismatch"):
        render_trials.verify_source_digest(source, LOCAL, digests)


def test_missing_private_mapping_is_rejected(tmp_path):
    # Check that even an old inline hash cannot stand in for an explicit mapping.
    local = dict(LOCAL, sha256=hashlib.sha256(b"test").hexdigest())
    with pytest.raises(ValueError, match=rf'{local["id"]} requires --private-digests'):
        render_trials.verify_source_digest(
            tmp_path / "not-read", local, render_trials.load_private_digests(None)
        )


def test_invalid_private_mapping_is_rejected(tmp_path):
    mapping = tmp_path / "private-digests.json"
    for value in ("a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n", 123, None):
        mapping.write_text(json.dumps({LOCAL["id"]: value}), encoding="utf-8")
        with pytest.raises(ValueError, match="exactly 64 hexadecimal"):
            render_trials.load_private_digests(mapping)
    for invalid_json in ("{", "[]"):
        mapping.write_text(invalid_json, encoding="utf-8")
        with pytest.raises(ValueError, match="--private-digests.*JSON object"):
            render_trials.load_private_digests(mapping)


@pytest.mark.parametrize(
    "item", [item for item in render_trials.CATALOG if item["location"] == "local"],
    ids=lambda item: item["id"],
)
def test_local_catalog_uses_neutral_filenames(item):
    assert item["file"] == item["id"] + Path(item["file"]).suffix
    assert item["private_digest_required"] is True
    assert "sha256" not in item


def test_public_fixture_still_uses_original_hash():
    public = next(item for item in render_trials.CATALOG if item["id"] == "ZH01")
    assert public["sha256"] == "a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b"
    source = SCRIPT.parents[1] / "fixtures" / public["file"]
    render_trials.verify_source_digest(source, public, {})
    render_trials.verify_source_digest(source, public, {public["id"]: "0" * 64})


@pytest.mark.parametrize("location", ["fixture", "external", "unknown"])
def test_private_files_reject_non_local_ids(tmp_path, location):
    sid = next(
        (item["id"] for item in render_trials.CATALOG if item["location"] == location),
        "UNKNOWN-SYNTHETIC-ID",
    )
    mapping = tmp_path / "files.json"
    mapping.write_text(json.dumps({sid: "synthetic.mp3"}), encoding="utf-8")
    with pytest.raises(ValueError, match="--private-files.*local"):
        render_trials.load_private_files(mapping)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"MC01": "one.mp3", "MC01": "two.mp3"}',
        '{"MC01": 1}',
        '{"MC01": null}',
        '{"MC01": ""}',
        '{"MC01": "  "}',
        r'{"MC01": "bad\u0000path.mp3"}',
    ],
    ids=["malformed", "array", "duplicate", "number", "null", "empty", "blank", "nul"],
)
def test_invalid_private_files_mapping(tmp_path, text):
    mapping = tmp_path / "files.json"
    mapping.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="--private-files"):
        render_trials.load_private_files(mapping)


@pytest.fixture
def synthetic_trial(tmp_path, monkeypatch):
    item = dict(LOCAL, file=LOCAL["id"] + ".mp3")
    monkeypatch.setattr(render_trials, "CATALOG", [item])
    local = tmp_path / "local"
    local.mkdir()
    return item, SimpleNamespace(
        version="0.1.1",
        local=local,
        private_files=tmp_path / "files.json",
        private_digests=tmp_path / "digests.json",
        output=tmp_path / "output",
        snapshot=tmp_path / "snapshot.zip",
        only=[item["id"]],
        resume=True,
    )


@pytest.mark.parametrize("mode", ["default", "relative", "absolute"])
def test_render_uses_same_input_for_preflight_and_render(synthetic_trial, monkeypatch, mode):
    item, args = synthetic_trial
    sid = item["id"]
    if mode == "default":
        source = args.local / item["file"]
    elif mode == "relative":
        source = args.local / "nested" / "synthetic input.mp3"
        args.private_files.write_text(
            json.dumps({sid: "nested/synthetic input.mp3"}), encoding="utf-8"
        )
    else:
        source = args.local.parent / "synthetic input.mp3"
        args.private_files.write_text(json.dumps({sid: str(source)}), encoding="utf-8")
    source.parent.mkdir(exist_ok=True)
    raw = b"synthetic corpus bytes"
    source.write_bytes(raw)
    args.private_digests.write_text(
        json.dumps({sid: hashlib.sha256(raw).hexdigest()}), encoding="utf-8"
    )
    args.snapshot.write_bytes(b"synthetic snapshot placeholder")
    events = []
    original_digest = render_trials.digest

    def digest(path):
        if path != args.snapshot:
            events.append(("digest", path))
        return original_digest(path)

    def prepare(document, *_):
        events.append(("prepare", Path(document["source"])))
        metadata = {"path": document["source"], "channels": 2}
        pcm = np.zeros((8, 2))
        return SimpleNamespace(
            original=pcm, output=pcm, metadata=metadata,
            analysis={"source_metadata": metadata}, measured={"lufs": -24}, document=document,
        )

    # Only the DSP boundary is replaced; CLI, preflight hashing and reporting run normally.
    monkeypatch.setattr(render_trials, "digest", digest)
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.setitem(sys.modules, "vox", SimpleNamespace(
        __version__=args.version,
        audioio=SimpleNamespace(encode=lambda *_, **__: None),
        service=SimpleNamespace(SR=8, prepare=prepare, tuning_plan=lambda *_, **__: {}),
    ))
    argv = [
        str(SCRIPT), args.version, "--local", str(args.local),
        "--private-digests", str(args.private_digests), "--snapshot", str(args.snapshot),
        "--output", str(args.output), "--only", sid,
    ]
    if mode != "default":
        argv += ["--private-files", str(args.private_files)]
    monkeypatch.setattr(sys, "argv", argv)
    render_trials.main()

    assert events == [(stage, source.resolve()) for stage in ("digest", "prepare", "prepare", "digest")]
    report = json.loads(
        (args.output / "engineering" / args.version / sid / "report.json").read_text(encoding="utf-8")
    )
    assert report["source"] == item
    assert report["input_spec"] == {"channels": 2}
    assert report["before"]["source_metadata"] == {"channels": 2}
    assert source.read_bytes() == raw


@pytest.mark.parametrize(
    "expected,error,message",
    [
        (None, ValueError, "requires --private-digests"),
        ("0" * 63, ValueError, "exactly 64 hexadecimal"),
        ("0" * 64, RuntimeError, "Input digest mismatch"),
    ],
    ids=["missing", "invalid", "mismatch"],
)
def test_mapped_input_requires_original_digest_before_outputs(synthetic_trial, expected, error, message):
    item, args = synthetic_trial
    source = args.local / "synthetic.mp3"
    source.write_bytes(b"synthetic corpus bytes")
    sid = item["id"]
    args.private_files.write_text(json.dumps({sid: source.name}), encoding="utf-8")
    args.private_digests.write_text(
        json.dumps({} if expected is None else {sid: expected}), encoding="utf-8"
    )
    with pytest.raises(error, match=message):
        render_trials.render(args)
    assert not args.snapshot.exists()
    assert not args.output.exists()


def test_resume_rejects_legacy_private_source_path(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({
            "source": dict(LOCAL, file="old-private-input.mp3"),
            "source_metadata": {"path": "/data/private-input.mp3"},
        }),
        encoding="utf-8",
    )
    assert not render_trials._resume_report_is_public(report, LOCAL)
    report.write_text(json.dumps({"source": LOCAL}), encoding="utf-8")
    assert render_trials._resume_report_is_public(report, LOCAL)


@pytest.mark.parametrize(
    "value",
    [
        r"\\server\share\recording.wav",
        r"\rooted\recording.wav",
        "//server/share/recording.wav",
        "C:relative-drive-path.mp3",
    ],
    ids=["unc-share", "rooted", "posix-unc", "drive-relative"],
)
def test_resume_rejects_rooted_paths_in_ordinary_string_fields(tmp_path, value):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"source": LOCAL, "notes": [value]}), encoding="utf-8")
    assert not render_trials._resume_report_is_public(report, LOCAL)


def test_resume_allows_neutral_notes(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"source": LOCAL, "notes": ["local corpus", "mc01"]}),
        encoding="utf-8",
    )
    assert render_trials._resume_report_is_public(report, LOCAL)
