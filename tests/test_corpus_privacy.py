import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("mc_corpus") / "render_trials.py"
SPEC = importlib.util.spec_from_file_location("corpus_render_trials", SCRIPT)
render_trials = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_trials)
LOCAL = next(item for item in render_trials.CATALOG if item["location"] == "local")


def test_private_mapping_verifies_input_bytes(tmp_path):
    assert LOCAL["private_digest_required"] is True
    assert "sha256" not in LOCAL
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


def test_public_fixture_still_uses_original_hash():
    public = next(item for item in render_trials.CATALOG if item["id"] == "ZH01")
    assert public["sha256"] == "a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b"
    source = SCRIPT.parents[1] / "fixtures" / public["file"]
    render_trials.verify_source_digest(source, public, {})
    render_trials.verify_source_digest(source, public, {public["id"]: "0" * 64})
