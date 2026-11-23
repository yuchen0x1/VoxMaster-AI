"""Custom version checks must not outlive or update a closed settings dialog."""
import threading

import pytest
from PySide6.QtWidgets import QDialog

from vox import settings_dialog

URL = "https://release.test/version"


class Response:
    status_code = 200

    def __init__(self, blocks):
        self.blocks = blocks
        self.closed = False
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def iter_content(self, _size):
        yield from self.blocks


def test_cancelled_check_does_not_start_request(monkeypatch):
    cancel = threading.Event()
    cancel.set()

    def unexpected(*_args, **_kwargs):
        pytest.fail("A cancelled check must not open a network request")

    monkeypatch.setattr(settings_dialog.requests, "get", unexpected)
    with pytest.raises(InterruptedError, match="取消"):
        settings_dialog.check_version(URL, cancel)


@pytest.mark.parametrize("at_eof", [False, True])
def test_cancelled_response_is_closed_and_not_parsed(monkeypatch, at_eof):
    cancel = threading.Event()

    def blocks():
        if not at_eof:
            cancel.set()
        yield b'{"version":"99.0.0"}'
        cancel.set()

    response = Response(blocks())
    monkeypatch.setattr(settings_dialog.requests, "get", lambda *_a, **_k: response)
    with pytest.raises(InterruptedError, match="取消"):
        settings_dialog.check_version(URL, cancel)
    assert response.closed


def test_check_rejects_oversized_content_length_before_reading(monkeypatch):
    response = Response(())
    response.headers = {"Content-Length": "65537"}
    monkeypatch.setattr(settings_dialog.requests, "get", lambda *_a, **_k: response)
    with pytest.raises(ValueError, match="超过 64 KiB"):
        settings_dialog.check_version(URL)
    assert response.closed


def test_check_has_a_total_deadline_for_trickling_responses(monkeypatch):
    clock = iter((100.0, 100.0, 131.0))
    monkeypatch.setattr(settings_dialog.time, "monotonic", lambda: next(clock))

    class SlowResponse(Response):
        def iter_content(self, _size):
            yield b"{\"version\":\"99.0.0\"}"

    response = SlowResponse(())
    monkeypatch.setattr(settings_dialog.requests, "get", lambda *_a, **_k: response)
    with pytest.raises(TimeoutError, match="超时"):
        settings_dialog.check_version(URL)
    assert response.closed


@pytest.fixture
def dialog(monkeypatch, qt_session_app):
    # Delay worker execution so close/reopen races are deterministic, with no network.
    tasks = []

    class DeferredThread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            tasks.append(self.target)

    monkeypatch.setattr(settings_dialog.threading, "Thread", DeferredThread)
    widget = settings_dialog.SettingsDialog({}, {})
    widget.url.setText(URL)
    yield widget, tasks
    widget.reject()
    widget.deleteLater()
    qt_session_app.processEvents()


def test_duplicate_version_check_starts_only_one_worker(dialog):
    widget, tasks = dialog
    widget._check()
    widget._check()
    assert len(tasks) == 1
    assert not widget.check.isEnabled()


@pytest.mark.parametrize("finish", ["accept", "reject", "close"])
def test_finishing_settings_cancels_check_and_stops_timer(dialog, finish):
    widget, tasks = dialog
    widget.show()
    widget._check()
    cancel = widget._check_cancel
    assert len(tasks) == 1 and widget._timer.isActive()
    getattr(widget, finish)()
    assert cancel.is_set()
    assert not widget._timer.isActive()
    assert widget.check.isEnabled()


def test_cancelled_worker_does_not_read_manifest(dialog, monkeypatch):
    widget, tasks = dialog
    widget._check()
    widget.reject()

    def unexpected(*_args, **_kwargs):
        pytest.fail("A worker cancelled before it starts must not open a request")

    monkeypatch.setattr(settings_dialog.requests, "get", unexpected)
    tasks[0]()
    widget._poll()
    assert "取消" in widget.update_status.text()


@pytest.mark.parametrize("old_finishes_first", [True, False])
def test_late_result_cannot_replace_reopened_check(dialog, monkeypatch, old_finishes_first):
    widget, tasks = dialog
    calls = []

    def check(url, cancel=None):
        calls.append((url, cancel))
        # Even an uncooperative checker that ignores cancellation cannot publish stale UI.
        return "旧结果" if cancel.is_set() else "本次结果"

    monkeypatch.setattr(settings_dialog, "check_version", check)
    widget._check()
    widget.reject()
    widget.show()
    widget._check()
    assert len(tasks) == 2
    order = (0, 1) if old_finishes_first else (1, 0)
    for index in order:
        tasks[index]()
        widget._poll()
    assert len(calls) == 2
    assert widget.update_status.text() == "本次结果"
    assert widget.check.isEnabled()
    assert not widget._timer.isActive()


def test_worker_failure_restores_check_button(dialog, monkeypatch):
    widget, tasks = dialog

    def fail(*_args, **_kwargs):
        raise ValueError("错误的清单")

    monkeypatch.setattr(settings_dialog, "check_version", fail)
    widget._check()
    tasks[0]()
    widget._poll()
    assert widget.check.isEnabled()
    assert "错误的清单" in widget.update_status.text()
    assert not widget._timer.isActive()


def test_invalid_settings_do_not_cancel_a_running_check(dialog):
    widget, _tasks = dialog
    widget._check()
    cancel = widget._check_cancel
    widget.url.setText("file:///not-a-manifest")
    widget.accept()
    assert widget.result() != QDialog.DialogCode.Accepted
    assert not cancel.is_set()
    assert widget._timer.isActive()
    assert not widget.check.isEnabled()


def test_real_worker_finishes_after_dialog_is_closed(monkeypatch, qt_session_app):
    started, finished = threading.Event(), threading.Event()

    def check(_url, cancel=None):
        started.set()
        try:
            assert cancel.wait(2), "Closing settings must signal the live worker"
            raise InterruptedError("检查已取消。")
        finally:
            finished.set()

    monkeypatch.setattr(settings_dialog, "check_version", check)
    widget = settings_dialog.SettingsDialog({}, {})
    try:
        widget.url.setText(URL)
        widget.show()
        widget._check()
        assert started.wait(2)
        widget.close()
        assert finished.wait(2)
        widget._poll()
        assert "取消" in widget.update_status.text()
        assert not widget._timer.isActive()
    finally:
        widget.reject()
        widget.deleteLater()
        qt_session_app.processEvents()


def test_thread_start_failure_is_recoverable(dialog, monkeypatch):
    widget, _tasks = dialog

    class FailedThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("线程暂不可用")

    monkeypatch.setattr(settings_dialog.threading, "Thread", FailedThread)
    widget._check()
    assert widget.check.isEnabled()
    assert not widget._timer.isActive()
    assert "线程暂不可用" in widget.update_status.text()
    assert widget._check_cancel is None
    assert widget.result() != QDialog.DialogCode.Accepted
