"""Session health markers: crash detection stays local and version-aware."""
import json

from vox import __version__, health


def test_graceful_session_leaves_no_notice(tmp_path):
    directory = tmp_path / 'data'
    health.mark_open(directory=directory)
    assert health.startup_notice(directory=directory)
    health.mark_closed(directory=directory)
    assert health.previous_session(directory)['graceful'] is True
    assert health.startup_notice(directory=directory) is None


def test_missing_or_corrupt_marker_is_not_an_error(tmp_path):
    assert health.previous_session(directory=tmp_path) is None
    assert health.startup_notice(directory=tmp_path) is None
    directory = tmp_path / 'data'
    directory.mkdir()
    (directory / health.MARKER_NAME).write_text('not json', 'utf-8')
    assert health.previous_session(directory=directory) is None
    assert health.startup_notice(directory=directory) is None


def test_marker_write_is_atomic_and_readable(tmp_path):
    directory = tmp_path / 'data'
    health.mark_open(directory=directory)
    path = directory / health.MARKER_NAME
    state = json.loads(path.read_text('utf-8'))
    assert state['version'] == __version__ and state['graceful'] is False
    assert not list(directory.glob('*.tmp'))
    # A second open replaces the whole marker instead of accumulating history.
    health.mark_open(directory=directory)
    again = json.loads(path.read_text('utf-8'))
    assert again['graceful'] is False and again['opened'] == state['opened']


def test_ungraceful_session_reports_version_change(tmp_path):
    directory = tmp_path / 'data'
    directory.mkdir()
    marker = directory / health.MARKER_NAME
    marker.write_text(json.dumps({'version': '9.9.9', 'graceful': False}), 'utf-8')
    notice = health.startup_notice(directory=directory)
    assert '9.9.9' in notice and '未正常退出' in notice
    marker.write_text(json.dumps({'version': __version__, 'graceful': False}), 'utf-8')
    notice = health.startup_notice(directory=directory)
    assert '9.9.9' not in notice and '未正常退出' in notice


def test_mark_closed_survives_missing_marker(tmp_path):
    # Closing without a prior open (e.g. wiped data directory) must not raise.
    health.mark_closed(directory=tmp_path)
