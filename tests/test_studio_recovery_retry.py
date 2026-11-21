"""Missing-source restoration remains retryable without exposing a partial session."""
from concurrent.futures import Future
from copy import deepcopy

import numpy as np
import pytest

from vox import audioio, studio
from vox.studio_session import Session


@pytest.fixture
def recovery_dialog(tmp_path, monkeypatch, qt_session_app):
    t = np.arange(4410) / 44100
    wave = (.06 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    samples = np.column_stack((wave, wave))
    missing = tmp_path / 'missing.wav'
    original = Session({'Vocal': samples}, 44100)
    original.import_clip('FX', 'external-fx', str(missing), samples, 0)
    state = original.saved_state()
    before = deepcopy(state)
    replacement = tmp_path / 'replacement.wav'
    audioio.encode(replacement, samples, 44100, 32)
    monkeypatch.setattr(studio.QTimer, 'singleShot', lambda *a: None)
    dialog = studio.StudioDialog({'Vocal': samples}, 44100, state=state)
    dialog.timer.stop()
    dialog.mix_timer.stop()
    yield dialog, state, replacement, samples
    assert state == before, 'Relinking must not mutate the caller\'s saved state.'
    dialog.future = None
    dialog.reject()
    dialog.deleteLater()
    qt_session_app.processEvents()


def complete_synchronously(dialog, monkeypatch, failure=None):
    def job(label, run, complete):
        dialog.cancel_job.clear()
        dialog.after_job = complete
        dialog.future = Future()
        try:
            if failure is not None:
                raise failure
            dialog.future.set_result(run())
        except Exception as exc:
            dialog.future.set_exception(exc)
        dialog._refresh()

    monkeypatch.setattr(dialog, '_job', job)


def test_cancelled_relink_keeps_retry_visible_and_partial_session_disabled(recovery_dialog, monkeypatch):
    dialog, state, replacement, samples = recovery_dialog
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: ('', ''))
    dialog._restore(deepcopy(state), {'Vocal': samples})
    assert not dialog._loaded and dialog.future is None
    assert not dialog.apply_button.isEnabled()
    button = getattr(dialog, 'restore_button', None)
    assert button is not None, 'A cancelled file picker needs an in-window recovery action.'
    assert not button.isHidden() and button.isEnabled()
    assert '重新定位' in dialog.status.text() and '请关闭' not in dialog.status.text()
    complete_synchronously(dialog, monkeypatch)
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(replacement), 'WAV'))
    button.click()
    dialog._tick()
    assert dialog._loaded and dialog.apply_button.isEnabled()
    assert dialog.restore_button.isHidden()
    assert dialog.state['external_sources']['external-fx'] == str(replacement.resolve())
    assert 'external-fx' in dialog.session.sources


@pytest.mark.parametrize('failure', [InterruptedError('cancelled'), OSError('temporary read failure')])
def test_restore_task_failure_or_cancel_can_retry_without_reopening(recovery_dialog, monkeypatch, failure):
    dialog, state, replacement, samples = recovery_dialog
    previous = dialog.session
    errors = []
    monkeypatch.setattr(dialog, '_error', lambda exc: errors.append(str(exc)))
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(replacement), 'WAV'))
    complete_synchronously(dialog, monkeypatch, failure)
    dialog._restore(deepcopy(state), {'Vocal': samples})
    dialog._tick()
    assert dialog.future is None and not dialog._loaded
    assert dialog.session is previous and not dialog.apply_button.isEnabled()
    button = getattr(dialog, 'restore_button', None)
    assert button is not None and button.isEnabled() and not button.isHidden()
    assert bool(errors) == (not isinstance(failure, InterruptedError))
    complete_synchronously(dialog, monkeypatch)
    button.click()
    dialog._tick()
    assert dialog._loaded and dialog.session is not previous
    assert dialog.apply_button.isEnabled() and dialog.restore_button.isHidden()
    assert dialog._pending_restore is None


@pytest.mark.parametrize('invalid', ['corrupt', 'short'])
def test_failed_existing_candidate_can_be_reselected(recovery_dialog, tmp_path, monkeypatch, invalid):
    dialog, state, replacement, samples = recovery_dialog
    candidate = tmp_path / 'invalid-candidate.wav'
    if invalid == 'corrupt':
        candidate.write_bytes(b'not a supported audio stream')
    else:
        audioio.encode(candidate, samples[:100], 44100, 32)
    selections = iter([candidate, replacement])
    defaults, errors = [], []

    def choose(*args, **kwargs):
        defaults.append(args[2] if len(args) > 2 else None)
        return str(next(selections)), 'WAV'

    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', choose)
    monkeypatch.setattr(dialog, '_error', lambda exc: errors.append(str(exc)))
    complete_synchronously(dialog, monkeypatch)
    dialog._restore(deepcopy(state), {'Vocal': samples})
    dialog._tick()
    assert errors and not dialog._loaded
    assert not dialog.apply_button.isEnabled()
    dialog._retry_restore()
    dialog._tick()
    assert dialog._loaded and len(defaults) == 2
    assert defaults[1] == str(candidate), 'Keep the failed candidate as the picker default, not as a forced source.'
    assert dialog.state['external_sources']['external-fx'] == str(replacement.resolve())


def test_cancelled_second_picker_keeps_first_successful_location(recovery_dialog, monkeypatch):
    dialog, state, replacement, samples = recovery_dialog
    pending = deepcopy(state)
    pending['external_sources']['second-fx'] = 'missing-second.wav'
    clip = deepcopy(pending['tracks']['FX']['clips'][0])
    clip.update(source='second-fx', at=len(samples))
    pending['tracks']['FX']['clips'].append(clip)
    selections = iter([str(replacement), '', str(replacement)])
    titles = []

    def choose(*args, **kwargs):
        titles.append(args[1])
        return next(selections), 'WAV'

    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', choose)
    complete_synchronously(dialog, monkeypatch)
    dialog._restore(pending, {'Vocal': samples})
    assert not dialog._loaded and dialog.future is None
    dialog._retry_restore()
    dialog._tick()
    assert dialog._loaded and len(titles) == 3
    assert 'missing-second.wav' in titles[-1]
    assert set(dialog.state['external_sources']) == {'external-fx', 'second-fx'}


def test_closed_dialog_does_not_start_queued_initial_restore(recovery_dialog, monkeypatch, qt_session_app):
    _, state, _, samples = recovery_dialog
    queued, errors, prompts = [], [], []
    monkeypatch.setattr(studio.QTimer, 'singleShot', lambda delay, callback: queued.append(callback))
    dialog = studio.StudioDialog({'Vocal': samples}, 44100, state=state)
    dialog.timer.stop()
    monkeypatch.setattr(dialog, '_error', lambda exc: errors.append(str(exc)))
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (prompts.append(True) or '', ''))
    try:
        dialog.reject()
        assert len(queued) == 1
        queued[0]()
        assert not prompts and not errors and dialog.future is None
    finally:
        dialog.deleteLater()
        qt_session_app.processEvents()


def test_incomplete_session_cannot_be_accepted_programmatically(recovery_dialog):
    dialog, _, _, _ = recovery_dialog
    dialog.accept()
    assert dialog.result() != studio.QDialog.Accepted
    assert not dialog.closing and not dialog._loaded
    assert dialog.restore_button.isEnabled()


def test_real_restore_thread_is_cancelled_and_joined_before_close(recovery_dialog, monkeypatch):
    import threading

    dialog, state, replacement, samples = recovery_dialog
    started = threading.Event()
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(replacement), 'WAV'))

    def waiting_source(candidate, tracks, cancel):
        started.set()
        assert cancel.wait(5), 'Closing must request cooperative cancellation.'
        raise InterruptedError()

    monkeypatch.setattr(studio, 'load_sources', waiting_source)
    dialog._restore(deepcopy(state), {'Vocal': samples})
    assert started.wait(5)
    future = dialog.future
    dialog.reject()
    assert dialog.closing and dialog.cancel_job.is_set()
    with pytest.raises(InterruptedError):
        future.result(timeout=5)
    dialog._tick()
    assert dialog.future is None and not dialog._loaded
    assert dialog.result() == studio.QDialog.Rejected
    assert dialog.executor._shutdown


def test_late_cancel_drops_restored_draft_and_allows_retry(recovery_dialog, monkeypatch):
    dialog, state, replacement, samples = recovery_dialog
    original = dialog.session
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(replacement), 'WAV'))
    complete_synchronously(dialog, monkeypatch)
    dialog._restore(deepcopy(state), {'Vocal': samples})
    dialog.cancel_job.set()
    dialog._tick()
    assert dialog.session is original and not dialog._loaded
    assert dialog.restore_button.isEnabled()
    dialog._retry_restore()
    dialog._tick()
    assert dialog._loaded and dialog.session is not original


def test_retry_is_disabled_while_restoration_is_running(recovery_dialog, monkeypatch):
    dialog, state, replacement, samples = recovery_dialog
    monkeypatch.setattr(studio.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(replacement), 'WAV'))
    calls = []

    def pending(label, run, complete):
        calls.append(label)
        dialog.future = Future()
        dialog.after_job = complete
        dialog._refresh()

    monkeypatch.setattr(dialog, '_job', pending)
    dialog._restore(deepcopy(state), {'Vocal': samples})
    button = getattr(dialog, 'restore_button', None)
    assert button is not None and not button.isEnabled()
    button.click()
    dialog._retry_restore()
    assert len(calls) == 1
    assert not dialog.apply_button.isEnabled()
