"""A GUI result is revalidated after preparation and immediately before checkpoint commit."""
from copy import deepcopy
from threading import Event
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
