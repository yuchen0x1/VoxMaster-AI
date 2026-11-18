"""Exercise desktop entry points against a licensed speech recording."""

import time
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog
from vox import audioio, storage, interface
from vox.dialogs import ExportDialog, ParameterDialog
from vox.studio import StudioDialog

SPEECH = Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav"


def settle(app, window, errors):
    deadline = time.monotonic() + 90
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.015)
    assert window.worker is None
    assert not errors, errors


def test_window_workflow(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    monkeypatch.setattr(interface, "ROOT", tmp_path)
    monkeypatch.setattr(interface.MainWindow, "detect", lambda self: None)
    window = interface.MainWindow()
    errors = []
    monkeypatch.setattr(window, "notice", errors.append)
    window.open_path(SPEECH)
    settle(app, window, errors)
    assert window.s.output is None and window.s.original_wave.shape[1] == 2
    window.style.setCurrentIndex(2)
    window.go.click()
    settle(app, window, errors)
    tuned = window.s.output.copy()
    assert not np.array_equal(tuned, window.s.original)
    assert window.b.isChecked()
    window.a.click()
    assert window.audio() is window.s.original
    window.b.click()
    assert window.audio() is window.s.output

    def edit(d):
        d.inputs["target_lufs"].setValue(-21)
        return 1

    monkeypatch.setattr(ParameterDialog, "exec", edit)
    window.parameters()
    settle(app, window, errors)
    assert window.s.document["params"]["target_lufs"] == -21.0
    window.travel(False)
    settle(app, window, errors)
    assert np.array_equal(tuned, window.s.output)
    window.travel(True)
    settle(app, window, errors)
    assert window.s.document["params"]["target_lufs"] == -21.0
    monkeypatch.setattr(StudioDialog, "exec", lambda d: 1)
    window.studio()
    settle(app, window, errors)
    assert window.s.document["studio"]["schema"] == 1
    expected = window.s.output.copy()
    proj = tmp_path / "mix.voxproj"
    target = tmp_path / "master.wav"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(proj), ""))
    window.save()
    window.save()
    assert list((tmp_path / "mix.voxproj.history").glob("*.voxproj"))
    window.open_path(proj)
    settle(app, window, errors)
    np.testing.assert_array_equal(window.s.output, expected)
    monkeypatch.setattr(ExportDialog, "exec", lambda self: 1)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    window.export_btn.click()
    settle(app, window, errors)
    data, meta = audioio.decode(target)
    assert meta["bit_depth"] == 24
    np.testing.assert_allclose(data, expected, atol=3e-7)
    assert storage.load_project(window.last_autosave)["source"] == str(SPEECH.resolve())
    window.close()


def test_protect_unrelated_project(tmp_path):
    path = tmp_path / "unrelated.voxproj"
    path.write_text('{"important":"existing"}')
    with pytest.raises(ValueError):
        storage.save_project(path, storage.project())
    assert path.read_text() == '{"important":"existing"}'
