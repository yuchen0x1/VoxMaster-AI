"""One QApplication for the whole pytest session.

Individual tests used to create `QApplication.instance() or QApplication([])` as
function locals, so the first app was garbage-collected mid-run and later tests
instantiated fresh ones; the final teardown then deleted Qt objects in an
arbitrary order and glibc aborted at interpreter exit (exit code 134 on
ubuntu-24.04). A single session-scoped app, flushed at session end, keeps
construction and destruction deterministic on every runner.
"""
import gc

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='session', autouse=True)
def qt_session_app():
    app = QApplication.instance() or QApplication(['VoxMaster AI tests'])
    yield app
    gc.collect()
    # Flush pending deletions and close stray top-level widgets while the app
    # is still alive, so no child outlives its application.
    for _ in range(2):
        for widget in list(QApplication.topLevelWidgets()):
            widget.close()
        app.processEvents()
        gc.collect()
