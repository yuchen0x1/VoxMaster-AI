"""GUI publication is guarded by cancellation and an atomic recovery checkpoint."""
from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
from threading import Event

import pytest

from vox import interface, models_store, service
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
