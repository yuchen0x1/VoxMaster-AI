import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from vox import storage


def test_project_roundtrip_preserves_relative_asset_semantics(tmp_path):
    project_path = tmp_path / "session.voxproj"
    doc = storage.project(tmp_path / "recording.wav", "回归工程")
    doc.update(
        reference=str(tmp_path / "guide.wav"),
        stems={"Vocal": str(tmp_path / "vocal.wav")},
        studio={"schema": 1, "external_sources": {"FX": str(tmp_path / "effect.wav")}},
    )

    storage.save_project(project_path, doc, backup=False)

    raw = json.loads(project_path.read_text(encoding="utf-8"))
    assert raw["source"] == "recording.wav"
    assert raw["reference"] == "guide.wav"
    assert raw["stems"] == {"Vocal": "vocal.wav"}
    assert raw["studio"]["external_sources"] == {"FX": "effect.wav"}
    loaded = storage.load_project(project_path)
    assert loaded["source"] == str((tmp_path / "recording.wav").resolve())
    assert loaded["reference"] == str((tmp_path / "guide.wav").resolve())
    assert loaded["stems"] == {"Vocal": str((tmp_path / "vocal.wav").resolve())}
    assert loaded["studio"]["external_sources"] == {
        "FX": str((tmp_path / "effect.wav").resolve())
    }


def test_version_one_project_with_omitted_optional_fields_remains_compatible(tmp_path):
    path = tmp_path / "legacy.voxproj"
    storage.write_json(path, {"version": 1, "source": "legacy.wav"})

    loaded = storage.load_project(path)

    assert loaded["source"] == str((tmp_path / "legacy.wav").resolve())
    assert loaded["reference"] == ""
    assert loaded["stems"] == {}
    assert loaded["studio"] is None
    assert loaded["params"] == {}
    assert loaded["history"] == []


def test_empty_optional_media_references_remain_empty_on_load(tmp_path):
    path = tmp_path / "empty-media.voxproj"
    raw = storage.project("recording.wav")
    raw["stems"] = {"Vocal": "", "Instrumental": "backing.wav"}
    raw["studio"] = {"schema": 1, "external_sources": {"FX": ""}}
    storage.write_json(path, raw)

    loaded = storage.load_project(path)

    assert loaded["stems"]["Vocal"] == ""
    assert loaded["stems"]["Instrumental"] == str((tmp_path / "backing.wav").resolve())
    assert loaded["studio"]["external_sources"]["FX"] == ""


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("reference", None),
        ("stems", ["vocal.wav"]),
        ("stems", {"Vocal": 3}),
        ("studio", [1]),
        ("studio", {"external_sources": ["effect.wav"]}),
        ("studio", {"external_sources": {"FX": 5}}),
        ("name", 3),
        ("history", None),
        ("history", [1]),
        ("history", ["valid entry", None]),
        ("params", []),
    ],
)
def test_load_project_rejects_malformed_field_types(tmp_path, field, bad_value):
    path = tmp_path / "damaged.voxproj"
    raw = storage.project("recording.wav")
    raw[field] = bad_value
    storage.write_json(path, raw)

    with pytest.raises(ValueError, match="工程字段"):
        storage.load_project(path)


def test_package_check_failed_assertion_remains_failure_under_optimization(tmp_path):
    report = tmp_path / "package-report.json"
    child = textwrap.dedent(
        """
        import sys
        from PySide6.QtGui import QIcon
        from vox import package_check, visual
        visual.app_icon = lambda: QIcon()
        raise SystemExit(package_check.main([sys.argv[1]]))
        """
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-O", "-c", child, str(report)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "FAIL"
    assert "应用图标资源为空" in evidence["error"]
