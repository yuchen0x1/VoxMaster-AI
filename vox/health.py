"""Local session health markers for post-update diagnosis. Offline only; no telemetry.

The marker file records one GUI session. A session is only marked graceful after
``app.exec`` returns normally, so a crash, force kill or power loss leaves it
untouched and the next start can surface a gentle notice.
"""
import json
import os
import time
from pathlib import Path

from . import __version__
from .platforms import data_directory

MARKER_NAME = 'session-state.json'


def marker_path(directory=None):
    return Path(data_directory() if directory is None else directory) / MARKER_NAME


def _write(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), 'utf-8')
    os.replace(temp, path)


def mark_open(now=None, directory=None):
    """Start a session marker, keeping no history beyond the last session."""
    _write(marker_path(directory), {
        'version': __version__,
        'opened': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime((now or time.time()))),
        'graceful': False,
    })


def mark_closed(now=None, directory=None):
    path = marker_path(directory)
    try:
        state = json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        return
    if isinstance(state, dict):
        state['graceful'] = True
        state['closed'] = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now or time.time()))
        _write(path, state)


def previous_session(directory=None):
    """Return the previous session marker, or None when absent or unreadable."""
    try:
        state = json.loads(marker_path(directory).read_text('utf-8'))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def startup_notice(directory=None):
    """A short, actionable line for the last ungraceful session; None when fine."""
    last = previous_session(directory)
    if not last or last.get('graceful'):
        return None
    if last.get('version') not in (None, __version__):
        return ('上次会话（版本 ' + str(last.get('version')) + '）未正常退出。'
                '工程自动保存与版本备份仍可用；若更新后反复出现，请通过 GitHub Issues 反馈。')
    return ('上次会话未正常退出，可能是程序异常或系统断电。'
            '工程自动保存与版本备份仍可用。')
