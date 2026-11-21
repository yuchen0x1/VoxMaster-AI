"""A GUI result is revalidated after preparation and immediately before checkpoint commit."""
from copy import deepcopy
from threading import Event, get_ident

from PySide6.QtCore import QTimer
import os

import numpy as np
import pytest

from vox import audioio, interface, service
from vox.jobs import Worker
from vox.storage import load_project, project, save_project
from vox.studio_session import Session as StudioSession


def tone(frequency, seconds=1.0):
    time = np.arange(round(service.SR * seconds)) / service.SR
    wave = .08 * np.sin(2 * np.pi * frequency * time)
    return np.column_stack((wave, wave)).astype(np.float32)


@pytest.fixture
def prepared_candidate(tmp_path, monkeypatch, qt_session_app):
    recovery_root = tmp_path / 'data'
    monkeypatch.setattr(interface, 'ROOT', recovery_root)
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)

    source = tmp_path / 'source.wav'
    external = tmp_path / 'external.wav'
    audioio.encode(source, tone(220), service.SR, 32)
    audioio.encode(external, tone(440), service.SR, 32)

    window = interface.MainWindow()
    window.timer.stop()
    previous = service.prepare(project(source), Event(), lambda *_: None)
    window.commit(previous, reset=True)
    window.undo_stack.append({'history': 'keep'})
    window.redo_stack.append({'history': 'keep redo'})

    external_audio, _ = audioio.decode(external)
    timeline = StudioSession({'Vocal': previous.original}, service.SR)
    timeline.import_clip('FX', 'effect/one', str(external), external_audio, 0)
    document = deepcopy(previous.document)
    document['studio'] = timeline.saved_state()
    candidate = service.prepare(document, Event(), lambda *_: None, previous)

    # Stand in for a separately published export/recovery pair. A rejected GUI
    # commit must not try to roll back or remove user-visible published files.
    published = tmp_path / 'published'
    published.mkdir()
    artifact = published / 'master.wav'
    recovery = published / 'Separated.voxproj'
    artifact.write_bytes(b'already-published master')
    save_project(recovery, candidate.document, False)
    candidate.publication_committed = True
    candidate.publication_project = str(recovery)

    yield {'window': window, 'previous': previous, 'candidate': candidate,
           'external': external, 'source': source, 'artifact': artifact,
           'recovery': recovery, 'app': qt_session_app}
    window.worker = None
    window.close()
    window.deleteLater()
    qt_session_app.processEvents()


def replace_with_same_stat(path):
    before = path.stat()
    original = service.file_hash(path)
    samples, _ = audioio.decode(path)
    replacement = path.with_name('replacement.wav')
    audioio.encode(replacement, -samples, service.SR, 32)
    assert replacement.stat().st_size == before.st_size
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, path)
    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert service.file_hash(path) != original


@pytest.mark.parametrize('mutation', ['same-stat-replacement', 'delete'])
def test_commit_rejects_external_media_changed_after_prepare_and_preserves_checkpoint(
        prepared_candidate, mutation):
    state = prepared_candidate
    window, candidate = state['window'], state['candidate']
    current = window.s
    checkpoint = window.last_autosave
    checkpoint_before = checkpoint.read_bytes()
    identity = window.recovery_id
    undo, redo = deepcopy(window.undo_stack), deepcopy(window.redo_stack)
    current_path = window.path
    artifact_before = state['artifact'].read_bytes()
    recovery_before = state['recovery'].read_bytes()
    stop_calls = []
    stop = window.stop
    window.stop = lambda: (stop_calls.append(True), stop())

    if mutation == 'same-stat-replacement':
        original_hash = service.file_hash(state['external'])
        replace_with_same_stat(state['external'])
        assert service.file_hash(state['external']) != original_hash
    else:
        state['external'].unlink()

    with pytest.raises((ValueError, OSError), match='素材|media|No such file|系统找不到'):
        window.commit(candidate, path='new-project.voxproj', reset=True)

    assert window.s is current
    assert window.path == current_path
    assert window.recovery_id == identity
    assert window.last_autosave == checkpoint
    assert checkpoint.read_bytes() == checkpoint_before
    assert window.undo_stack == undo and window.redo_stack == redo
    assert not stop_calls
    assert state['artifact'].read_bytes() == artifact_before
    assert state['recovery'].read_bytes() == recovery_before
    assert state['external'].exists() is (mutation != 'delete')


def test_commit_accepts_unchanged_prepared_media_and_writes_checkpoint(prepared_candidate):
    state = prepared_candidate
    window, candidate = state['window'], state['candidate']
    previous = window.s

    assert window.commit(candidate) is None

    assert window.s is candidate and window.s is not previous
    assert window.last_autosave.is_file()
    saved = load_project(window.last_autosave)
    assert saved['studio'] == candidate.document['studio']
    assert window.undo_stack[-1] == previous.document


def test_late_cancel_still_commits_published_result_when_media_is_unchanged(prepared_candidate):
    state = prepared_candidate
    window, candidate = state['window'], state['candidate']
    worker = Worker(lambda *_: None, window)
    worker.cancel.set()
    window.worker = worker
    received = []

    window.job_success(lambda result: (window.commit(result), received.append(result)), candidate)

    assert received == [candidate]
    assert window.s is candidate
    assert window.last_autosave.is_file()


def test_full_commit_hashing_does_not_block_gui_events(prepared_candidate, monkeypatch):
    state = prepared_candidate
    window, candidate, app = state['window'], state['candidate'], state['app']
    entered, release = Event(), Event()
    gui_thread, hash_threads, ticks, errors = get_ident(), [], [], []
    real_hash = service.file_hash

    def held_hash(path, cancel=None):
        hash_threads.append(get_ident())
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test did not release media verification')
        return real_hash(path, cancel)

    monkeypatch.setattr(service, 'file_hash', held_hash)
    monkeypatch.setattr(window, 'notice', errors.append)
    window.run_job('verify media', lambda *_: candidate, window.commit_render)
    worker = window.worker
    try:
        assert entered.wait(2), 'full validation must start before GUI result delivery'
        QTimer.singleShot(0, lambda: ticks.append(True))
        app.processEvents()
        assert ticks and window.s is state['previous']
        assert window.worker is worker
    finally:
        release.set()
        assert worker.wait(10_000)
        app.processEvents()
    assert not errors
    assert hash_threads and gui_thread not in hash_threads
    assert window.s is candidate and window.worker is None


@pytest.mark.parametrize('mutation', ['same-stat-replacement', 'delete'])
def test_published_validation_failure_names_recovery_project(prepared_candidate, mutation):
    state = prepared_candidate
    if mutation == 'delete':
        state['external'].unlink()
    else:
        replace_with_same_stat(state['external'])

    with pytest.raises((ValueError, OSError), match='可从以下工程恢复') as error:
        state['window'].commit_render(state['candidate'])

    assert str(state['recovery']) in str(error.value)
    assert state['window'].s is state['previous']
    assert state['artifact'].is_file() and state['recovery'].is_file()


def test_media_replaced_after_worker_validation_is_rejected_at_gui_boundary(
        prepared_candidate, monkeypatch):
    state = prepared_candidate
    window, candidate, app = state['window'], state['candidate'], state['app']
    errors = []
    before = window.last_autosave.read_bytes()
    monkeypatch.setattr(window, 'notice', errors.append)
    window.run_job('verify media', lambda *_: candidate, window.commit_render)
    worker = window.worker
    assert worker.wait(10_000)
    replace_with_same_stat(state['external'])
    app.processEvents()

    assert window.s is state['previous'] and window.worker is None
    assert window.last_autosave.read_bytes() == before
    assert len(errors) == 1 and str(state['recovery']) in errors[0]


def test_late_worker_callbacks_cannot_clear_or_commit_a_new_job(prepared_candidate):
    state = prepared_candidate
    window = state['window']
    old = Worker(lambda *_: None, window)
    current = Worker(lambda *_: None, window)
    window.worker = current
    received = []

    window.job_success(received.append, state['candidate'], job=old)
    window.job_finished(old)

    assert received == [] and window.s is state['previous']
    assert window.worker is current
    window.worker = None
    old.deleteLater()
    current.deleteLater()


@pytest.mark.parametrize('published', [False, True], ids=['draft', 'published'])
def test_close_during_validation_waits_for_worker_and_preserves_publication_semantics(
        prepared_candidate, monkeypatch, published):
    from PySide6.QtGui import QCloseEvent

    state = prepared_candidate
    window, candidate, app = state['window'], state['candidate'], state['app']
    candidate.publication_committed = published
    entered, release = Event(), Event()
    errors = []
    real_hash = service.file_hash

    def held_hash(path, cancel=None):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test did not release media verification')
        return real_hash(path, cancel)

    monkeypatch.setattr(service, 'file_hash', held_hash)
    monkeypatch.setattr(window, 'notice', errors.append)
    window.run_job('verify media', lambda *_: candidate, window.commit_render)
    worker = window.worker
    try:
        assert entered.wait(2)
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted() and worker.cancel.is_set()
        assert window.worker is worker
    finally:
        release.set()
        assert worker.wait(10_000)
        app.processEvents()
    assert not errors and window.worker is None
    assert window.s is (candidate if published else state['previous'])
    assert state['artifact'].is_file() and state['recovery'].is_file()


def test_late_cancel_cannot_hide_published_validation_error(prepared_candidate, monkeypatch):
    state = prepared_candidate
    window, candidate, app = state['window'], state['candidate'], state['app']
    entered, release = Event(), Event()
    errors = []
    real_hash = service.file_hash

    def held_hash(path, cancel=None):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test did not release media verification')
        return real_hash(path, cancel)

    monkeypatch.setattr(service, 'file_hash', held_hash)
    monkeypatch.setattr(window, 'notice', errors.append)
    window.run_job('verify media', lambda *_: candidate, window.commit_render)
    worker = window.worker
    try:
        assert entered.wait(2)
        window.cancel()
        state['external'].unlink()
    finally:
        release.set()
        assert worker.wait(10_000)
        app.processEvents()
    assert window.s is state['previous'] and window.worker is None
    assert len(errors) == 1 and str(state['recovery']) in errors[0]
    assert state['artifact'].is_file() and state['recovery'].is_file()


def test_commit_receipt_is_bound_to_expected_hashes_and_media_paths(prepared_candidate):
    state = prepared_candidate
    candidate = state['candidate']
    receipt = service.verify_session_media(candidate)
    candidate.media_hashes['original'] = '0' * 64
    with pytest.raises(ValueError, match='素材已变更'):
        service.verify_media_receipt(candidate, receipt)


def test_interrupted_validation_is_not_wrapped_as_publication_failure(
        prepared_candidate, monkeypatch):
    state = prepared_candidate
    window, app = state['window'], state['app']
    errors = []

    def interrupted(*_args, **_kwargs):
        raise InterruptedError()

    monkeypatch.setattr(service, 'file_hash', interrupted)
    monkeypatch.setattr(window, 'notice', errors.append)
    window.run_job('verify media', lambda *_: state['candidate'], window.commit_render)
    worker = window.worker
    assert worker.wait(10_000)
    app.processEvents()
    assert not errors and window.s is state['previous'] and window.worker is None
    assert '已取消' in window.progress_text.text()
    assert state['artifact'].is_file() and state['recovery'].is_file()
