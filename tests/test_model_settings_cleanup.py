"""Failed model settings writes must preserve the config and remove scratch."""

from pathlib import Path

import pytest

from vox import models_store as store


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_failed_settings_write_removes_temporary_file(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(store, "app_data", lambda: tmp_path)
    store.save_settings(mode="CPU")
    target = tmp_path / "model-center.json"
    before = target.read_bytes()

    def denied(*args, **kwargs):
        raise OSError("settings write denied")

    if failure == "write":
        monkeypatch.setattr(store.json, "dump", denied)
    else:
        monkeypatch.setattr(Path, "replace", denied)

    with pytest.raises(OSError, match="settings write denied"):
        store.save_settings(mode="DirectML")

    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]
