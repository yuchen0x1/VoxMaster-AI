"""A recent-list preference failure must not misreport a committed project write."""
from copy import deepcopy
from dataclasses import replace
from threading import Event
import time

import numpy as np
import pytest

from vox import audioio, interface, service
from vox.storage import load_project, project, save_project


@pytest.fixture
def window(tmp_path, monkeypatch, qt_session_app):
    monkeypatch.setattr(interface, 'ROOT', tmp_path / 'data')
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)
    source = tmp_path / 'source.wav'
    audioio.encode(source, np.zeros((service.SR // 2, 2), dtype=np.float32), service.SR, 32)
    current = service.prepare(project(source), Event(), lambda *_: None)
    result = interface.MainWindow()
    result.timer.stop()
    result.commit(current, reset=True)
    result.notices = []
    monkeypatch.setattr(result, 'notice', result.notices.append)
    yield result
    if result.worker:
        result.worker.cancel.set()
        result.worker.wait(5000)
        qt_session_app.processEvents()
    result.close()
    result.deleteLater()
    qt_session_app.processEvents()


def deny_recent_settings(window, monkeypatch):
    def denied():
        raise PermissionError('settings.json is read-only')
    monkeypatch.setattr(window, 'save_settings', denied)


def finish_job(window, app):
    deadline = time.monotonic() + 5
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert window.worker is None


def test_open_checkpoint_commits_and_reports_only_recent_warning(window, tmp_path, monkeypatch,
                                                               qt_session_app):
    document = deepcopy(window.s.document)
    document['name'] = 'successfully opened project'
    target = tmp_path / 'opened.voxproj'
    save_project(target, document)
    window.undo_stack.append(deepcopy(window.s.document))
    window.redo_stack.append(deepcopy(window.s.document))
    deny_recent_settings(window, monkeypatch)

    window.open_path(str(target))
    finish_job(window, qt_session_app)

    assert window.s.document['name'] == document['name']
    assert window.path == str(target)
    assert not window.undo_stack and not window.redo_stack
    assert load_project(window.last_autosave)['name'] == document['name']
    assert not window.notices
    assert '最近工程记录未保存' in window.progress_text.text()
    assert '任务未完成' not in window.progress_text.text()


@pytest.mark.parametrize('as_new', [False, True])
def test_saved_project_survives_recent_preferences_failure(window, tmp_path, monkeypatch, as_new):
    target = tmp_path / 'saved.voxproj'
    window.undo_stack.append(deepcopy(window.s.document))
    history = deepcopy(window.undo_stack)
    deny_recent_settings(window, monkeypatch)
    if as_new:
        monkeypatch.setattr(interface.QFileDialog, 'getSaveFileName', lambda *_: (str(target), ''))
    else:
        window.path = str(target)

    window.save(as_new)

    assert load_project(target)['source'] == window.s.document['source']
    assert window.path == str(target)
    assert window.undo_stack == history
    assert not window.notices
    assert '工程已保存' in window.progress_text.text()
    assert '最近工程记录未保存' in window.progress_text.text()


def test_checkpoint_failure_still_preserves_session_and_undo(window, monkeypatch):
    current = window.s
    history = [deepcopy(current.document)]
    window.undo_stack[:] = history
    old_path = window.path
    old_settings = deepcopy(window.settings)
    changed = replace(current, document={**current.document, 'name': 'uncommitted'})

    def disk_full(*_):
        raise OSError('checkpoint disk full')

    monkeypatch.setattr(interface, 'save_project', disk_full)
    with pytest.raises(OSError, match='checkpoint disk full'):
        window.commit(changed, path='new.voxproj', reset=True)
    assert window.s is current and window.path == old_path
    assert window.undo_stack == history and window.settings == old_settings


def test_project_write_failure_remains_a_failure_without_recent_update(window, monkeypatch, tmp_path):
    target = tmp_path / 'not-saved.voxproj'
    window.path = str(target)
    settings = deepcopy(window.settings)

    def disk_full(*_):
        raise OSError('project disk full')

    monkeypatch.setattr(interface, 'save_project', disk_full)
    window.save()
    assert not target.exists()
    assert window.settings == settings
    assert window.notices == ['project disk full']
    assert window.progress_text.text() == '任务未完成'


@pytest.mark.parametrize('recent', [None, 7, 'not a list', {'invalid': True}, [None, 7, {}]])
def test_malformed_recent_preference_does_not_fail_saved_project(window, tmp_path, recent):
    target = tmp_path / 'saved-with-bad-recent.voxproj'
    window.path = str(target)
    window.settings['recent'] = recent
    window.save()
    assert load_project(target)['source'] == window.s.document['source']
    assert not window.notices
    assert '工程已保存' in window.progress_text.text()
    assert window.settings['recent'] == [str(target)]


def test_successful_recent_write_still_persists_order_and_limit(window, tmp_path):
    target = tmp_path / 'recent.voxproj'
    window.settings['recent'] = [str(target), *(str(tmp_path / f'{i}.voxproj') for i in range(20))]
    assert window.remember(target) is None
    assert window.settings['recent'][0] == str(target)
    assert len(window.settings['recent']) == 16
    assert window.settings['recent'].count(str(target)) == 1
    import json
    saved = json.loads((interface.ROOT / 'settings.json').read_text(encoding='utf-8'))
    assert saved['recent'] == window.settings['recent']
