"""GUI publication is guarded by cancellation and an atomic recovery checkpoint."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
from threading import Event

import pytest

from vox import audioio, interface, models_store, service
from vox.jobs import Worker
from vox.storage import load_project, project

FIXTURE = Path(__file__).parent / 'fixtures/fleurs-mandarin.wav'


@pytest.fixture
def window(tmp_path, monkeypatch, qt_session_app):
    monkeypatch.setattr(interface, 'ROOT', tmp_path)
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)
    result = interface.MainWindow()
    result.timer.stop()
    current = service.prepare(project(FIXTURE), Event(), lambda *_: None)
    result.commit(current, reset=True)
    yield result
    result.worker = None
    result.close()
    result.deleteLater()
    qt_session_app.processEvents()


def test_failed_recovery_write_preserves_live_session_and_history(window, monkeypatch):
    current = window.s
    recovery, identity = window.last_autosave, window.recovery_id
    document = deepcopy(current.document)
    document['name'] = 'new pending revision'
    history = list(window.undo_stack)

    def disk_full(*args, **kwargs):
        raise OSError('No space left for checkpoint')

    monkeypatch.setattr(interface, 'save_project', disk_full)
    with pytest.raises(OSError, match='checkpoint'):
        window.commit(replace(current, document=document))
    assert window.s is current
    assert window.last_autosave == recovery and window.recovery_id == identity
    assert window.undo_stack == history and not window.redo_stack


def test_queued_cancel_rejects_draft_but_delivers_already_published_result(window):
    worker = Worker(lambda *_: None, window)
    worker.cancel.set()
    window.worker = worker
    received = []
    window.job_success(received.append, replace(window.s, publication_committed=False))
    assert not received and '保留上一版本' in window.progress_text.text()
    published = replace(window.s, publication_committed=True)
    window.job_success(received.append, published)
    assert received == [published]


@pytest.mark.parametrize('already_written', [False, True], ids=['before-publish', 'after-publish'])
def test_export_cancellation_reports_disk_outcome(window, tmp_path, monkeypatch, qt_session_app,
                                                 already_written):
    target = tmp_path / 'export.wav'
    window.s.output = window.s.original[:4410]
    window.s.measured = window.s.analysis
    monkeypatch.setattr(interface.ExportDialog, 'exec', lambda self: True)
    monkeypatch.setattr(interface.ExportDialog, 'value', lambda self: ('wav', 44100, 24, 2))
    monkeypatch.setattr(interface.QFileDialog, 'getSaveFileName', lambda *_: (str(target), ''))
    real_encode = audioio.encode
    at_boundary, resume = Event(), Event()

    def held_encode(*args, **kwargs):
        if already_written:
            real_encode(*args, **kwargs)
        at_boundary.set()
        if not resume.wait(10):
            raise RuntimeError('test did not release encoder')
        if not already_written:
            real_encode(*args, **kwargs)

    monkeypatch.setattr(audioio, 'encode', held_encode)
    window.export()
    worker = window.worker
    assert worker is not None
    try:
        assert at_boundary.wait(10)
        window.cancel()
    finally:
        resume.set()
        assert worker.wait(10_000)
        qt_session_app.processEvents()
    assert window.worker is None
    if already_written:
        assert window.progress_text.text() == '已导出 · ' + str(target)
        decoded, _ = audioio.decode(target)
        assert decoded.shape == window.s.output.shape
    else:
        assert '已取消' in window.progress_text.text()
        assert not target.exists()
    assert not list(tmp_path.glob('.vox-*.part'))


def test_published_song_checkpoint_failure_reports_recoverable_project(window, tmp_path, monkeypatch):
    configured = os.getenv('VOX_MODEL_TEST_WEIGHTS')
    weights = Path(configured) if configured else models_store.directory()
    try:
        models_store.verify(weights)
    except (OSError, ValueError) as exc:
        pytest.skip(f'Local fixed model weights required: {exc}')
    output = tmp_path / 'published'
    output.mkdir()
    current = window.s
    history = list(window.undo_stack)
    published = service.separate_project(
        current, output, Event(), lambda *_: None, root=weights, mode='CPU',
        song_options={'target': 'natural', 'master': 'conservative'},
    )

    def disk_full(*args, **kwargs):
        raise OSError('No space left for checkpoint')

    monkeypatch.setattr(interface, 'save_project', disk_full)
    with pytest.raises(OSError, match='可从以下工程恢复') as error:
        window.commit_render(published)
    assert published.publication_project in str(error.value)
    assert window.s is current and window.undo_stack == history
    recovered = service.prepare(load_project(published.publication_project), Event(), lambda *_: None)
    assert recovered.document['stems'] == published.document['stems']
    assert recovered.document['song'] == published.document['song']
    assert recovered.document['separation']['status'] == 'verified'
    assert (recovered.output == published.output).all()
