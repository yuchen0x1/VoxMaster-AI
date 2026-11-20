"""Source selection must reject links before traversing private directory trees."""
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from scripts import source_archive


def source_root(tmp_path):
    root = tmp_path / 'source'
    (root / 'scripts').mkdir(parents=True)
    (root / 'LICENSE').write_text('test license', encoding='utf-8')
    (root / 'scripts' / 'public.py').write_text('pass', encoding='utf-8')
    return root


def test_private_directory_is_pruned_before_scanning(tmp_path, monkeypatch):
    root = source_root(tmp_path)
    private = root / 'scripts' / '.AuDiT'
    private.mkdir()
    (private / 'private.py').write_text('private sentinel', encoding='utf-8')
    original = os.scandir

    def scan(path):
        if Path(path) == private:
            raise AssertionError('private directories must not be traversed')
        return original(path)

    monkeypatch.setattr(os, 'scandir', scan)
    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'scripts/public.py'}


def test_reparse_attribute_is_recognized_without_path_is_junction():
    class Reparse:
        def lstat(self):
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)

    assert source_archive._is_link(Reparse())


def test_unreadable_source_tree_preserves_previous_archive(tmp_path, monkeypatch):
    root = source_root(tmp_path)
    denied = root / 'scripts' / 'denied'
    denied.mkdir()
    original = os.scandir

    def scan(path):
        if Path(path) == denied:
            raise PermissionError('cannot audit source directory')
        return original(path)

    monkeypatch.setattr(os, 'scandir', scan)
    output = tmp_path / 'source.zip'
    output.write_bytes(b'previous approved archive')
    with pytest.raises(PermissionError, match='cannot audit'):
        source_archive.archive(output, root)
    assert output.read_bytes() == b'previous approved archive'
    assert not list(tmp_path.glob('.vox-source-*'))


@pytest.mark.skipif(os.name != 'nt', reason='junctions are Windows-specific')
def test_junction_cycle_is_not_traversed(tmp_path):
    root = source_root(tmp_path)
    junction = root / 'scripts' / 'cycle'
    result = subprocess.run(
        ['cmd.exe', '/c', 'mklink', '/J', str(junction), str(junction.parent)],
        check=False, capture_output=True, timeout=30,
    )
    if result.returncode:
        pytest.skip(f'junction creation is unavailable: {result.stderr.strip()}')
    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'scripts/public.py'}
