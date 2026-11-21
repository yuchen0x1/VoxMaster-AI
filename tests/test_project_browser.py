"""The recovery browser must survive damaged ancillary settings and stale files."""
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidget

from vox import interface
from vox.storage import project, save_project


@pytest.fixture
def browser(tmp_path, monkeypatch, qt_session_app):
    monkeypatch.setattr(interface, 'ROOT', tmp_path / 'data')
    monkeypatch.setattr(interface, 'preferences', lambda: {})
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)
    window = interface.MainWindow()
    window.timer.stop()
    entries = []

    def inspect(dialog):
        assert dialog.windowTitle() == '我的项目'
        files = dialog.findChild(QListWidget)
        entries.extend(
            (files.item(i).text(), files.item(i).data(Qt.UserRole))
            for i in range(files.count())
        )
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, 'exec', inspect)
    yield window, entries
    window.close()
    window.deleteLater()
    qt_session_app.processEvents()


def checkpoint(path, name):
    save_project(path, project(name=name), False)
    return path


@pytest.mark.parametrize('recent', [None, 7, True, 'not a list', {'invalid': True}, [None, 7, {}]])
def test_bad_recent_does_not_hide_recovery(browser, recent):
    window, entries = browser
    target = checkpoint(interface.ROOT / 'recovery' / 'saved.voxproj', 'recoverable session')
    window.settings['recent'] = recent
    before = deepcopy(window.settings)

    window.projects()

    assert len(entries) == 1
    assert entries[0][1] == str(target)
    assert 'recoverable session' in entries[0][0]
    assert window.settings == before


def test_mixed_recent_keeps_valid_projects_without_rewriting_settings(browser, tmp_path):
    window, entries = browser
    target = checkpoint(tmp_path / 'recent.voxproj', 'valid recent')
    window.settings['recent'] = [None, 7, {}, '', str(target), str(tmp_path / 'missing.voxproj')]
    before = deepcopy(window.settings)

    window.projects()

    assert [path for _, path in entries] == [str(target)]
    assert window.settings == before


def test_unreadable_recent_does_not_hide_other_projects(browser, tmp_path, monkeypatch):
    window, entries = browser
    target = checkpoint(tmp_path / 'good.voxproj', 'readable')
    denied = tmp_path / 'inaccessible' / 'bad.voxproj'
    window.settings['recent'] = [str(denied), str(target)]
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == denied:
            raise PermissionError('unavailable media')
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)

    window.projects()

    assert [path for _, path in entries] == [str(target)]


def test_recovery_disappearing_during_sort_does_not_hide_valid_checkpoint(browser, monkeypatch):
    window, entries = browser
    target = checkpoint(interface.ROOT / 'recovery' / 'good.voxproj', 'surviving recovery')
    missing = checkpoint(interface.ROOT / 'recovery' / 'gone.voxproj', 'stale recovery')
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == missing:
            raise FileNotFoundError('checkpoint removed by another session')
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)

    window.projects()

    assert [path for _, path in entries] == [str(target)]


def test_project_removed_after_read_does_not_abort_browser(browser, tmp_path, monkeypatch):
    window, entries = browser
    gone = checkpoint(tmp_path / 'gone.voxproj', 'removed after loading')
    target = checkpoint(tmp_path / 'good.voxproj', 'surviving recent')
    window.settings['recent'] = [str(gone), str(target)]
    original_load = interface.load_project

    def load(path):
        document = original_load(path)
        if path == gone:
            path.unlink()
        return document

    monkeypatch.setattr(interface, 'load_project', load)

    window.projects()

    assert [path for _, path in entries] == [str(target)]
