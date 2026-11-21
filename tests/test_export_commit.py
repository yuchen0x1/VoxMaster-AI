"""Fault timing uses real encoding/publication, not mocked audio processing."""
from concurrent.futures import Future
import json
import os
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from vox import audioio, interface, studio
from vox.jobs import Worker


@pytest.fixture
def samples():
    t = np.arange(4410) / 44100
    wave = .08 * np.sin(2 * np.pi * 330 * t)
    return np.column_stack((wave, wave)).astype(np.float32)


def cancel_after_publication(monkeypatch, destination, cancel):
    name = 'rename' if os.name == 'nt' else 'link'
    publish = getattr(audioio.os, name)

    def committed(source, target, *args, **kwargs):
        result = publish(source, target, *args, **kwargs)
        if Path(target) == destination:
            cancel.set()
        return result

    monkeypatch.setattr(audioio.os, name, committed)


@pytest.mark.parametrize('extension', ['wav', 'flac', 'mp3', 'aac'])
def test_worker_delivers_real_export_if_cancel_arrives_after_commit(tmp_path, monkeypatch, samples, extension):
    target = tmp_path / ('export.' + extension)
    successes, cancellations, failures = [], [], []
    worker = Worker(lambda cancel, _: audioio.encode(target, samples, 44100, cancel=cancel))
    cancel_after_publication(monkeypatch, target, worker.cancel)
    worker.succeeded.connect(successes.append)
    worker.cancelled.connect(lambda: cancellations.append(True))
    worker.failed.connect(failures.append)
    worker.run()
    assert worker.cancel.is_set()
    assert not cancellations and not failures
    assert len(successes) == 1
    assert successes[0].publication_committed
    assert successes[0].path == target
    decoded, _ = audioio.decode(target)
    assert len(decoded) >= len(samples) - 2048 and np.isfinite(decoded).all()
    assert list(tmp_path.iterdir()) == [target]


def test_cancel_before_publication_removes_temporary_and_does_not_publish(tmp_path, monkeypatch, samples):
    target = tmp_path / 'export.wav'
    cancel = Event()
    check = audioio._check_cancel
    checks = []

    def before_commit(event):
        checks.append(True)
        # Initial check, one PCM block, then the final pre-publication check.
        if len(checks) == 3:
            cancel.set()
        check(event)

    monkeypatch.setattr(audioio, '_check_cancel', before_commit)
    with pytest.raises(InterruptedError):
        audioio.encode(target, samples, 44100, cancel=cancel)
    assert len(checks) == 3
    assert not list(tmp_path.iterdir())


def test_concurrent_destination_wins_without_overwrite(tmp_path, monkeypatch, samples):
    target = tmp_path / 'export.wav'
    name = 'rename' if os.name == 'nt' else 'link'
    publish = getattr(audioio.os, name)

    def collision(source, destination, *args, **kwargs):
        Path(destination).write_bytes(b'existing finished audio')
        return publish(source, destination, *args, **kwargs)

    monkeypatch.setattr(audioio.os, name, collision)
    with pytest.raises(FileExistsError):
        audioio.encode(target, samples, 44100)
    assert target.read_bytes() == b'existing finished audio'
    assert list(tmp_path.iterdir()) == [target]


def test_main_window_delivers_export_when_cancel_is_queued_after_worker(tmp_path, monkeypatch, qt_session_app, samples):
    monkeypatch.setattr(interface, 'ROOT', tmp_path / 'data')
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)
    window = interface.MainWindow()
    window.timer.stop()
    worker = Worker(lambda *_: None, window)
    received = []
    try:
        result = audioio.encode(tmp_path / 'export.wav', samples, 44100)
        worker.cancel.set()
        window.worker = worker
        window.job_success(received.append, result)
        assert received == [result]
        assert '取消' not in window.progress_text.text()
    finally:
        window.worker = None
        window.close()
        window.deleteLater()
        qt_session_app.processEvents()


@pytest.mark.parametrize('cleanup_failure', [False, True])
def test_studio_export_preserves_receipt_through_future_and_late_cancel(tmp_path, monkeypatch, qt_session_app, samples, cleanup_failure):
    dialog = studio.StudioDialog({'Vocal': samples}, 44100)
    dialog.timer.stop()
    dialog.mix_timer.stop()
    target = tmp_path / 'track.wav'
    monkeypatch.setattr(studio.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), 'WAV'))
    cancel_after_publication(monkeypatch, target, dialog.cancel_job)
    if cleanup_failure:
        unlink = Path.unlink

        def cleanup_error(path, *args, **kwargs):
            if path.parent == tmp_path and path.name.startswith('.vox-'):
                raise PermissionError('temporary cleanup denied')
            return unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, 'unlink', cleanup_error)

    def completed_job(label, run, complete):
        future = Future()
        future.set_result(run())
        dialog.future = future
        dialog.after_job = complete

    monkeypatch.setattr(dialog, '_job', completed_job)
    try:
        dialog._export()
        assert dialog.cancel_job.is_set() and target.is_file()
        dialog._tick()
        assert dialog.future is None
        if cleanup_failure:
            assert dialog.status.text().startswith(f'已导出 {target}')
            assert 'temporary cleanup denied' in dialog.status.text()
        else:
            assert dialog.status.text() == f'已导出 {target}'
            assert list(tmp_path.iterdir()) == [target]
    finally:
        dialog.future = None
        dialog.reject()
        dialog.deleteLater()
        qt_session_app.processEvents()


@pytest.mark.parametrize('late_cancel', [False, True])
def test_post_commit_cleanup_error_is_a_warning_not_a_failed_export(tmp_path, monkeypatch, samples, late_cancel):
    target = tmp_path / 'export.wav'
    successes, failures, cancellations = [], [], []
    worker = Worker(lambda cancel, _: audioio.encode(target, samples, 44100, cancel=cancel))
    if late_cancel:
        cancel_after_publication(monkeypatch, target, worker.cancel)
    unlink = Path.unlink

    def cleanup_error(path, *args, **kwargs):
        if path.parent == tmp_path and path.name.startswith('.vox-') and path.suffix == '.part':
            raise PermissionError('temporary cleanup denied')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', cleanup_error)
    worker.succeeded.connect(successes.append)
    worker.failed.connect(failures.append)
    worker.cancelled.connect(lambda: cancellations.append(True))
    worker.run()
    assert not failures and not cancellations
    assert len(successes) == 1 and successes[0].publication_committed
    assert 'temporary cleanup denied' in successes[0].warning
    decoded, _ = audioio.decode(target)
    assert len(decoded) == len(samples) and np.isfinite(decoded).all()


def test_cli_exposes_post_commit_cleanup_warning_in_json(tmp_path, monkeypatch, capsys, samples):
    from vox import cli

    source = tmp_path / 'source.wav'
    output = tmp_path / 'output'
    output.mkdir()
    audioio.encode(source, samples, 44100, 32)
    unlink = Path.unlink

    def cleanup_error(path, *args, **kwargs):
        if path.parent == output and path.name.startswith('.vox-'):
            raise PermissionError('temporary cleanup denied')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', cleanup_error)
    status = cli.main(['tune', str(source), '--output-dir', str(output)])
    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    result = payload['results'][0]
    assert 'error' not in result and Path(result['output']).is_file()
    assert 'temporary cleanup denied' in result['warnings'][0]


def test_studio_draft_still_honours_queued_cancellation(qt_session_app, samples):
    dialog = studio.StudioDialog({'Vocal': samples}, 44100)
    dialog.timer.stop()
    dialog.mix_timer.stop()
    received = []
    try:
        dialog.future = Future()
        dialog.future.set_result(samples)
        dialog.after_job = received.append
        dialog.cancel_job.set()
        dialog._tick()
        assert not received and dialog.status.text() == '已取消任务'
    finally:
        dialog.reject()
        dialog.deleteLater()
        qt_session_app.processEvents()
