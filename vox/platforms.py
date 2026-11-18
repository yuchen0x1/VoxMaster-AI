"""OS conventions shared by the desktop, CLI and model centre."""
import os
from pathlib import Path
import sys


def data_directory(environ=None, system=None, home=None):
    env = os.environ if environ is None else environ
    system = sys.platform if system is None else system
    home = Path.home() if home is None else Path(home)
    if env.get('VOXMASTER_DATA'):
        return Path(env['VOXMASTER_DATA']).expanduser()
    if system == 'win32':
        return Path(env.get('LOCALAPPDATA', home / 'AppData/Local')) / 'VoxMasterAI'
    if system == 'darwin':
        return home / 'Library/Application Support/VoxMasterAI'
    return Path(env.get('XDG_DATA_HOME', home / '.local/share')) / 'VoxMasterAI'


def ui_font():
    return {'win32': 'Microsoft YaHei UI', 'darwin': 'PingFang SC'}.get(sys.platform, 'Noto Sans CJK SC')
