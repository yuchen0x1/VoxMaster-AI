"""Offline model-center cancellation, bounded metadata reads and QThread ownership.

Only HTTP responses/worker startup are substituted. Storage, locks, hashes and
Qt threads/signals are real; no weights or audio inference are needed.
"""

import hashlib
import io
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QWidget
from shiboken6 import isValid

from vox import models, models_store as store


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("VOXMASTER_DATA", str(tmp_path / "config"))
    payloads = {"vocals.onnx": b"tiny vocal model", "accompaniment.onnx": b"tiny backing model"}
    monkeypatch.setattr(
        store, "FILES",
        {name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in payloads.items()},
    )
    monkeypatch.setattr(store, "SIZE", sum(map(len, payloads.values())))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Lifecycle tests must not access the network")

    monkeypatch.setattr(models.urllib.request, "urlopen", unexpected)
    return payloads


def flush(app):
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def wait(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
        app.processEvents()
    assert predicate(), "Model-center Qt event timed out"


def click(button):
    assert button.isEnabled(), button.text()
    QTest.mouseClick(button, Qt.LeftButton)


@pytest.fixture
def ui(qt_session_app, monkeypatch):
    widgets, tasks, releases, errors = [], [], [], []
    monkeypatch.setattr(sys, "excepthook", lambda _kind, exc, _tb: errors.append(exc))

    def make(parent=None):
        if parent is not None:
            widgets.append(parent)
        dialog = models.ModelDialog(parent)
        widgets.append(dialog)
        dialog.show()
        qt_session_app.processEvents()
        return dialog

    harness = SimpleNamespace(app=qt_session_app, make=make, tasks=tasks, releases=releases)
    yield harness
    # Always release a blocked real QThread, including on the unfixed red run.
    for release in releases:
        release.set()
    for widget in widgets:
        if isValid(widget) and getattr(widget, "task", None) is not None:
            tasks.append(widget.task)
    for task in tasks:
        if isValid(task):
            task.stop.set()
            assert task.wait(3000), "Test left a model worker running"
    flush(qt_session_app)
    for task in tasks:
        if isValid(task):
            task.deleteLater()
    for widget in reversed(widgets):
        if isValid(widget):
            widget.close()
            widget.deleteLater()
    flush(qt_session_app)
    assert not errors, f"Unhandled Qt slot errors: {errors!r}"


class Response(io.BytesIO):
    status = 200
    headers = {}

    def read1(self, size=-1):
        return self.read(size)


def blocked_upstream(ui, monkeypatch, stage):
    entered, release = threading.Event(), threading.Event()
    ui.releases.append(release)
    timeouts = []

    class BlockedResponse(Response):
        def read(self, size=-1):
            if stage == "body":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release metadata body")
            return super().read(size)

    response = BlockedResponse(json.dumps({"sha": store.REVISION}).encode())

    def urlopen(_url, *, timeout):
        timeouts.append(timeout)
        if stage == "open":
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release metadata connection")
        return response

    monkeypatch.setattr(models.urllib.request, "urlopen", urlopen)
    dialog = ui.make()
    click(dialog.update)
    task = dialog.task
    ui.tasks.append(task)
    assert entered.wait(2)
    return dialog, task, release, response, timeouts


@pytest.mark.parametrize("stage", ["open", "body"])
def test_slow_upstream_cancel_is_a_request_until_thread_finishes(ui, monkeypatch, storage, stage):
    root = store.directory()
    root.mkdir(parents=True)
    for name, body in storage.items():
        (root / name).write_bytes(body)
    part = root / "vocals.onnx.part"
    part.write_bytes(b"existing resumable download")
    dialog, task, release, response, timeouts = blocked_upstream(ui, monkeypatch, stage)
    click(dialog.cancel)
    assert task.stop.is_set()
    assert task.isRunning() and dialog.task is task
    assert not dialog.update.isEnabled() and not dialog.cancel.isEnabled()
    assert "取消" in dialog.message.text() and "等待" in dialog.message.text()
    pending = dialog.message.text()
    task.update.emit(.9, "late progress")
    task.result.emit("late success")
    ui.app.processEvents()
    assert dialog.message.text() == pending
    release.set()
    assert task.wait(3000)
    wait(ui.app, lambda: dialog.task is None)
    assert dialog.isVisible() and dialog.update.isEnabled()
    assert "取消" in dialog.message.text() and "上游版本" not in dialog.message.text()
    assert response.closed
    assert 0 < timeouts[0] <= 3
    assert part.read_bytes() == b"existing resumable download"
    store.verify()  # Canceling metadata must never discard installed or partial models.


@pytest.mark.parametrize("stage", ["open", "body"])
@pytest.mark.parametrize("method", ["button", "titlebar", "escape", "accept", "done"])
def test_close_requests_stop_then_closes_only_after_finished(ui, monkeypatch, stage, method):
    dialog, task, release, response, _ = blocked_upstream(ui, monkeypatch, stage)
    if method == "button":
        buttons = dialog.findChild(QDialogButtonBox)
        click(buttons.button(QDialogButtonBox.Close))
    elif method == "titlebar":
        assert not dialog.close()
    elif method == "escape":
        QTest.keyClick(dialog, Qt.Key_Escape)
    elif method == "accept":
        dialog.accept()
    else:
        dialog.done(QDialog.Rejected)
    assert task.stop.is_set()
    assert dialog.isVisible() and task.isRunning()
    assert dialog.close_pending and dialog.task is task
    pending = dialog.message.text()
    assert "等待" in pending
    release.set()
    assert task.wait(3000)
    wait(ui.app, lambda: not dialog.isVisible())
    assert dialog.task is None and response.closed
    assert dialog.message.text() == pending  # No late result/progress may replace closing status.


@pytest.mark.parametrize("destroy_parent", [False, True])
def test_destroyed_dialog_cancels_but_does_not_destroy_running_qthread(ui, monkeypatch, destroy_parent):
    entered, release = threading.Event(), threading.Event()
    ui.releases.append(release)

    def action(_cancel, progress):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release destroyed dialog worker")
        progress(1, "late progress after destruction")
        return "late result after destruction"

    parent = QWidget() if destroy_parent else None
    dialog = ui.make(parent)
    dialog._run(action)
    task = dialog.task
    ui.tasks.append(task)
    assert entered.wait(2)
    # Guard the red run against Qt's fatal "QThread: Destroyed while running".
    assert task.parent() is not dialog, "The running worker must not be owned by its dialog"
    target = parent if destroy_parent else dialog
    target.deleteLater()
    flush(ui.app)
    assert not isValid(dialog)
    assert isValid(task) and task.isRunning() and task.stop.is_set()
    release.set()
    assert task.wait(3000)
    wait(ui.app, lambda: not isValid(task))


@pytest.mark.parametrize("result_first", [False, True])
def test_result_cancel_race_does_not_publish_late_success(ui, result_first):
    entered, release = threading.Event(), threading.Event()
    ui.releases.append(release)

    def action(_cancel, progress):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release result/cancel race")
        progress(.9, "late progress")
        return "late success"

    dialog = ui.make()
    dialog._run(action)
    task = dialog.task
    ui.tasks.append(task)
    assert entered.wait(2)
    if result_first:
        # Queue both result and finished, but do not dispatch them before cancel.
        release.set()
        assert task.wait(3000)
    dialog._cancel()
    if not result_first:
        release.set()
        assert task.wait(3000)
    wait(ui.app, lambda: dialog.task is None)
    assert "取消" in dialog.message.text()
    assert "late" not in dialog.message.text() and dialog.progress.value() != 900
    assert dialog.update.isEnabled()


@pytest.mark.parametrize("failure", ["network", "json"])
def test_upstream_error_recovers_controls_and_can_retry(ui, monkeypatch, failure):
    def fail(*_args, **_kwargs):
        if failure == "network":
            raise TimeoutError("metadata socket timed out")
        return Response(b"not-json")

    monkeypatch.setattr(models.urllib.request, "urlopen", fail)
    dialog = ui.make()
    click(dialog.update)
    ui.tasks.append(dialog.task)
    wait(ui.app, lambda: dialog.task is None)
    assert "操作未完成" in dialog.message.text() and dialog.update.isEnabled()
    monkeypatch.setattr(
        models.urllib.request, "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps({"sha": store.REVISION}).encode()),
    )
    click(dialog.update)
    ui.tasks.append(dialog.task)
    wait(ui.app, lambda: dialog.task is None)
    assert dialog.message.text() == "当前已是上游版本"
    # Finished handling is idempotent even when there is no current sender/task.
    dialog._finished()
    assert dialog.task is None and dialog.update.isEnabled()


@pytest.mark.parametrize("signal", ["update", "result", "finished"])
def test_signal_wiring_failure_is_recoverable_without_starting_thread(ui, monkeypatch, signal):
    real_task, made = models.ModelTask, []

    class BrokenSignal:
        def connect(self, *_args):
            raise RuntimeError("signal wiring unavailable")

    def make_task(*args, **kwargs):
        task = real_task(*args, **kwargs)
        made.append(task)
        ui.tasks.append(task)
        if len(made) == 1:
            setattr(task, signal, BrokenSignal())
        return task

    monkeypatch.setattr(models, "ModelTask", make_task)
    dialog = ui.make()
    dialog._run(lambda *_args: "not started")
    assert not made[0].isRunning()
    assert dialog.task is None and dialog.update.isEnabled()
    assert "signal wiring unavailable" in dialog.message.text()
    dialog._run(lambda *_args: "retry succeeded")
    wait(ui.app, lambda: dialog.task is None)
    assert dialog.message.text() == "retry succeeded"


@pytest.mark.parametrize("after_start", [False, True])
def test_thread_start_failure_recovers_without_destroying_a_running_thread(ui, monkeypatch, after_start):
    real_start, calls = models.ModelTask.start, []
    entered, release = threading.Event(), threading.Event()
    ui.releases.append(release)

    def start(task, *args, **kwargs):
        calls.append(task)
        ui.tasks.append(task)
        if len(calls) == 1:
            if after_start:
                real_start(task, *args, **kwargs)
                assert entered.wait(2)
            raise RuntimeError("thread startup unavailable")
        return real_start(task, *args, **kwargs)

    def action(_cancel, _progress):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release failed startup")
        return "ignored after startup error"

    monkeypatch.setattr(models.ModelTask, "start", start)
    dialog = ui.make()
    dialog._run(action)
    assert "thread startup unavailable" in dialog.message.text()
    if after_start:
        assert entered.wait(2)
        assert dialog.task is calls[0] and calls[0].stop.is_set()
        assert calls[0].isRunning() and not dialog.update.isEnabled()
        release.set()
        assert calls[0].wait(3000)
        wait(ui.app, lambda: dialog.task is None)
    assert dialog.task is None and dialog.update.isEnabled()
    dialog._run(lambda *_args: "retry succeeded")
    wait(ui.app, lambda: dialog.task is None)
    assert dialog.message.text() == "retry succeeded"


@pytest.mark.parametrize("intent", ["pause", "cancel", "close"])
def test_download_stop_preserves_installation_and_only_cancel_discards_parts(
    ui, monkeypatch, storage, intent
):
    entered, release = threading.Event(), threading.Event()
    ui.releases.append(release)
    root = store.directory()
    root.mkdir(parents=True)
    for name, body in storage.items():
        (root / name).write_bytes(body)
    (root / "keep.txt").write_bytes(b"unrelated")
    payload = storage["vocals.onnx"]

    class DownloadResponse(Response):
        reads = 0

        def read(self, size=-1):
            self.reads += 1
            if self.reads == 1:
                return super().read(4)
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release download")
            return super().read(size)

    monkeypatch.setattr(
        models.urllib.request, "urlopen", lambda *_a, **_k: DownloadResponse(payload)
    )
    dialog = ui.make()
    click(dialog.start)
    task = dialog.task
    ui.tasks.append(task)
    assert entered.wait(2)
    if intent == "close":
        dialog.close()
    else:
        click(getattr(dialog, intent))
    assert task.stop.is_set() and task.isRunning()
    release.set()
    assert task.wait(3000)
    wait(ui.app, lambda: dialog.task is None)
    store.verify()
    assert (root / "keep.txt").read_bytes() == b"unrelated"
    assert bool(list(root.glob("*.part"))) is (intent != "cancel")
    assert dialog.isVisible() is (intent != "close")


def test_precancelled_upstream_never_opens_network(monkeypatch):
    cancel = threading.Event()
    cancel.set()
    opened = []
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_a, **_k: opened.append(True))
    with pytest.raises(InterruptedError):
        models.ModelDialog._upstream(cancel, lambda *_a: None)
    assert not opened


def test_continuous_trickle_has_total_deadline_and_does_not_use_filling_read(monkeypatch):
    class Trickle(Response):
        reads = 0

        def read(self, _size=-1):
            raise AssertionError("read(n) may fill forever on a trickling connection; use read1")

        def read1(self, _size=-1):
            self.reads += 1
            time.sleep(.005)
            return b" "

    response = Trickle()
    monkeypatch.setattr(models, "_UPSTREAM_DEADLINE", .025, raising=False)
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_a, **_k: response)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="超时|时限"):
        models.ModelDialog._upstream(threading.Event(), lambda *_a: None)
    assert time.monotonic() - started < .5
    assert 1 <= response.reads < 40 and response.closed


def test_deadline_is_checked_after_a_blocking_read_returns(monkeypatch):
    class SlowRead(Response):
        def read1(self, size=-1):
            time.sleep(.025)
            return super().read1(size)

    response = SlowRead(json.dumps({"sha": store.REVISION}).encode())
    monkeypatch.setattr(models, "_UPSTREAM_DEADLINE", .005, raising=False)
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_a, **_k: response)
    with pytest.raises(TimeoutError, match="超时|时限"):
        models.ModelDialog._upstream(threading.Event(), lambda *_a: None)
    assert response.closed


def test_cancel_after_last_bytes_skips_json_and_closes_response(monkeypatch):
    cancel = threading.Event()

    class CancelAtRead(Response):
        def read(self, size=-1):
            body = super().read(size)
            cancel.set()
            return body

    response = CancelAtRead(b"not-json-after-cancel")
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_a, **_k: response)
    with pytest.raises(InterruptedError):
        models.ModelDialog._upstream(cancel, lambda *_a: None)
    assert response.closed


def test_metadata_size_is_bounded_before_json_parsing(monkeypatch):
    response = Response(json.dumps({"sha": "x" * 100}).encode())
    monkeypatch.setattr(models, "_UPSTREAM_MAX_BYTES", 32, raising=False)
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_a, **_k: response)
    with pytest.raises(ValueError, match="大小|过大|上限"):
        models.ModelDialog._upstream(threading.Event(), lambda *_a: None)
    assert response.closed
