"""One QApplication for the whole pytest session and a deterministic exit.

Two failure modes motivated this design:

1. Individual tests used to create ``QApplication.instance() or QApplication([])``
   as function locals, so the first app was garbage-collected mid-run and later
   tests instantiated fresh ones, deleting Qt objects in an arbitrary order.
2. ``StudioDialog`` intentionally shuts down its render executor with
   ``shutdown(wait=False)``, so an idle VoxMix worker thread can outlive the
   session. Qt static teardown (DLL unload, ``QThreadStorage`` destruction)
   while that thread is still alive aborts the process with exit 134/139 on
   Linux runners and access violations inside ``exit()`` on Windows, even when
   every test passed.

The session fixture therefore keeps exactly one app alive for the whole run,
closes stray widgets, and wakes and joins every leftover ThreadPoolExecutor
worker before anything is torn down (mirroring CPython's own ``_python_exit``).
``pytest_unconfigure`` then exits with pytest's real status via a hard process
exit: all assertions have run and results.xml is written, so the exit code is
genuine and no DLL static destructor can turn a green run into a crash.
"""
import concurrent.futures.thread as _cf_thread
import gc
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

_KEPT_ALIVE = []


def _join_executor_workers(timeout=30):
    # Idle executor workers block on an internal queue; wake them first or the
    # join below would wait forever. Private CPython registry, guarded by getattr.
    registry = getattr(_cf_thread, '_threads_wakeups', None)
    if not registry:
        return
    for thread, wakeup in list(registry.items()):
        try:
            wakeup.wake()
            thread.join(timeout)
        except (RuntimeError, ValueError):
            pass


@pytest.fixture(scope='session', autouse=True)
def qt_session_app():
    app = QApplication.instance() or QApplication(['VoxMaster AI tests'])
    _KEPT_ALIVE.append(app)
    yield app
    # Flush pending deletions and close stray top-level widgets while the app
    # is still alive; the app itself is never deleted (see module docstring).
    for _ in range(2):
        for widget in list(QApplication.topLevelWidgets()):
            widget.close()
        app.processEvents()
    _join_executor_workers()
    gc.collect()


def pytest_unconfigure(config):
    status = int(getattr(config, 'exitstatus', 0) or 0)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except ValueError:
        pass
    if sys.platform == 'win32':
        # os._exit still runs C-level exit handlers on Windows, where Qt DLL
        # static destructors race the idle executor threads. TerminateProcess
        # skips them entirely, like os._exit does on POSIX. The pseudo-handle
        # must be passed as a 64-bit void pointer or Windows rejects it.
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), status)
    os._exit(status)
