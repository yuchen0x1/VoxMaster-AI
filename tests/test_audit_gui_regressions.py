"""Exercise real modal entry points and startup health state without sound/network I/O."""
import copy
import gc
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QMenu

from vox import health, interface, storage
from vox.dialogs import ParameterDialog
from vox.presets import DEFAULT
from vox.settings_dialog import SettingsDialog

NATIVE_EXEC = QDialog.exec


def flush_deletes(app):
    for _ in range(2):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    gc.collect()


def close_modal(monkeypatch, dialog_class, accept=False, edit=None):
    def execute(dialog):
        if edit:
            edit(dialog)
        QTimer.singleShot(0, dialog.accept if accept else dialog.reject)
        return NATIVE_EXEC(dialog)
    monkeypatch.setattr(dialog_class, 'exec', execute)


@pytest.fixture
def window(tmp_path, monkeypatch, qt_session_app):
    monkeypatch.setattr(storage, 'ROOT', tmp_path)
    monkeypatch.setattr(interface, 'ROOT', tmp_path)
    monkeypatch.setattr(interface.MainWindow, 'detect', lambda self: None)
    result = interface.MainWindow()
    result.timer.stop()
    qt_session_app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    flush_deletes(qt_session_app)


def test_settings_dialogs_are_released_after_each_close(window, monkeypatch, qt_session_app):
    close_modal(monkeypatch, SettingsDialog)
    for _ in range(5):
        window.settings_view()
        flush_deletes(qt_session_app)
        assert not window.findChildren(SettingsDialog)


def set_audio_session(window):
    audio = np.zeros((4410, 2), dtype='f')
    reference = weakref.ref(audio)
    window.s = SimpleNamespace(
        original=audio, output=None, sources={'Vocal': audio},
        vocal_report=None, analysis={}, document={'params': copy.deepcopy(DEFAULT)},
    )
    return reference


def test_closed_effect_dialog_releases_old_audio(window, monkeypatch, qt_session_app):
    close_modal(monkeypatch, ParameterDialog)
    reference = set_audio_session(window)
    window.parameters()
    window.s = None
    flush_deletes(qt_session_app)
    assert not window.findChildren(ParameterDialog)
    assert reference() is None


def test_effect_values_are_consumed_before_disposal(window, monkeypatch, qt_session_app):
    set_audio_session(window)
    close_modal(monkeypatch, ParameterDialog, accept=True,
                edit=lambda dialog: dialog.inputs['target_lufs'].setValue(-21))
    apply = Mock()
    monkeypatch.setattr(window, 'apply_params', apply)
    window.parameters()
    assert apply.call_args.args[0]['target_lufs'] == -21
    flush_deletes(qt_session_app)
    assert not window.findChildren(ParameterDialog)


def test_effect_dialog_disposed_when_result_handler_raises(window, monkeypatch, qt_session_app):
    set_audio_session(window)
    close_modal(monkeypatch, ParameterDialog, accept=True)
    monkeypatch.setattr(window, 'apply_params', Mock(side_effect=RuntimeError('apply failed')))
    with pytest.raises(RuntimeError, match='apply failed'):
        window.parameters()
    flush_deletes(qt_session_app)
    assert not window.findChildren(ParameterDialog)


@pytest.mark.parametrize('action', ['projects', 'library', 'report_text'])
def test_transient_plain_dialogs_are_released(window, action, monkeypatch, qt_session_app):
    close_modal(monkeypatch, QDialog)
    if action == 'report_text':
        window.report_text('Audit', 'Report')
    else:
        getattr(window, action)()
    flush_deletes(qt_session_app)
    assert not window.findChildren(QDialog)


def test_wave_menu_is_released(window, qt_session_app):
    def close_menu():
        for menu in window.findChildren(QMenu):
            menu.close()
    QTimer.singleShot(0, close_menu)
    window.wave_menu(QPoint(0, 0))
    flush_deletes(qt_session_app)
    assert not window.findChildren(QMenu)


def test_nested_official_update_dialog_is_released(window, monkeypatch, qt_session_app):
    from vox.update_dialog import UpdateDialog
    close_modal(monkeypatch, UpdateDialog)
    settings = SettingsDialog({}, {}, window)
    try:
        settings._official_update()
        flush_deletes(qt_session_app)
        assert not window.findChildren(UpdateDialog)
    finally:
        settings.deleteLater()
        flush_deletes(qt_session_app)


@pytest.mark.parametrize('previous', ['missing', 'graceful', 'ungraceful'])
def test_main_uses_previous_session_before_marking_open(previous, tmp_path, monkeypatch, qt_session_app):
    import app as entry

    path = tmp_path / health.MARKER_NAME
    monkeypatch.setattr(health, 'marker_path', lambda directory=None: path)
    if previous != 'missing':
        health.mark_open()
        if previous == 'graceful':
            health.mark_closed()
    application = Mock()

    def event_loop():
        assert health.previous_session()['graceful'] is False
        return 0

    application.exec.side_effect = event_loop
    status = QLabel('')
    fake_window = SimpleNamespace(show=lambda: None, progress_text=status)
    monkeypatch.setattr(entry, 'QApplication', lambda argv: application)
    monkeypatch.setattr(entry, 'MainWindow', lambda: fake_window)
    monkeypatch.setattr(entry.sys, 'argv', ['VoxMaster AI'])
    try:
        assert entry.main() == 0
        assert ('上次会话未正常退出' in status.text()) == (previous == 'ungraceful')
        assert health.previous_session()['graceful'] is True
    finally:
        status.deleteLater()
        flush_deletes(qt_session_app)


@pytest.mark.parametrize('fail_at', ['open', 'close'])
def test_optional_health_marker_failure_does_not_abort_app(fail_at, monkeypatch, capsys):
    import app as entry

    def cannot_write():
        raise PermissionError('test denied marker access')

    application = Mock()
    application.exec.return_value = 0
    main_window = Mock()
    mark_open, mark_closed = Mock(), Mock()
    (mark_open if fail_at == 'open' else mark_closed).side_effect = cannot_write
    monkeypatch.setattr(health, 'startup_notice', lambda: None)
    monkeypatch.setattr(health, 'mark_open', mark_open)
    monkeypatch.setattr(health, 'mark_closed', mark_closed)
    monkeypatch.setattr(entry, 'QApplication', lambda _: application)
    monkeypatch.setattr(entry, 'MainWindow', lambda: main_window)
    monkeypatch.setattr(entry, 'preferences', dict)
    monkeypatch.setattr(entry.sys, 'argv', ['VoxMaster AI'])

    assert entry.main() == 0
    main_window.show.assert_called_once()
    application.exec.assert_called_once()
    assert '会话诊断' in capsys.readouterr().err
    if fail_at == 'open':
        mark_closed.assert_not_called()
        main_window.progress_text.setText.assert_called_once_with('无法记录本次会话诊断；请检查数据目录权限。')
    else:
        mark_closed.assert_called_once()
