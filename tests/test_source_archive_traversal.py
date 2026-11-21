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


@pytest.fixture(params=[
    'symlink',
    pytest.param('junction', marks=pytest.mark.skipif(
        os.name != 'nt', reason='junctions are Windows-specific',
    )),
])
def directory_alias(request):
    created = []

    def make(link, target):
        if request.param == 'junction':
            # Junctions require no symlink privilege. On Windows these cases must
            # execute, not silently turn a missing security regression into a skip.
            result = subprocess.run(
                ['cmd.exe', '/c', 'mklink', '/J', str(link), str(target)],
                check=False, capture_output=True, timeout=30,
            )
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            created.append(link)
            assert link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        else:
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                pytest.skip(f'directory symlink creation is unavailable: {exc}')
            created.append(link)
        assert source_archive._is_link(link)
        return link

    yield make
    for link in reversed(created):
        if request.param == 'junction':
            link.rmdir()
        else:
            link.unlink()


def _forbid_resolve_and_writes(patch):
    def forbidden(*args, **kwargs):
        raise AssertionError('linked paths must be rejected before resolve, mkdir or write')

    patch.setattr(Path, 'resolve', forbidden)
    patch.setattr(Path, 'mkdir', forbidden)
    patch.setattr(Path, 'write_bytes', forbidden)
    patch.setattr(source_archive.tempfile, 'mkstemp', forbidden)
    patch.setattr(source_archive.os, 'replace', forbidden)


@pytest.mark.parametrize('dangling', [False, True], ids=['existing-target', 'dangling-target'])
def test_destination_file_symlink_is_rejected_before_resolve_or_write(
    tmp_path, monkeypatch, dangling,
):
    root = source_root(tmp_path)
    private = tmp_path / 'private.zip'
    private.write_bytes(b'private sentinel must not be overwritten')
    target = tmp_path / 'missing.zip' if dangling else private
    output = tmp_path / 'source.zip'
    try:
        output.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'file symlink creation is unavailable: {exc}')
    try:
        with monkeypatch.context() as patch:
            _forbid_resolve_and_writes(patch)
            with pytest.raises(ValueError, match='Archive destination.*(symlink|reparse)'):
                source_archive.archive(output, root)
        assert output.is_symlink()
        assert private.read_bytes() == b'private sentinel must not be overwritten'
        if dangling:
            assert not target.exists()
        assert not list(tmp_path.glob('.vox-source-*'))
    finally:
        output.unlink()


@pytest.mark.parametrize('placement', ['destination', 'parent', 'missing-parent', 'cancelled-parent'])
def test_destination_alias_is_rejected_before_resolve_mkdir_or_write(
    tmp_path, monkeypatch, directory_alias, placement,
):
    root = source_root(tmp_path)
    private = tmp_path / 'private'
    private.mkdir()
    sentinel = private / 'source.zip'
    sentinel.write_bytes(b'private sentinel must not be overwritten')
    alias = directory_alias(
        tmp_path / ('alias.zip' if placement == 'destination' else 'alias'), private,
    )
    if placement == 'destination':
        output = alias
    elif placement == 'parent':
        output = alias / 'source.zip'
    elif placement == 'missing-parent':
        output = alias / 'not-created' / 'source.zip'
    else:
        output = alias / '..' / 'source.zip'
        (tmp_path / 'source.zip').write_bytes(b'previous approved archive')

    with monkeypatch.context() as patch:
        _forbid_resolve_and_writes(patch)
        with pytest.raises(ValueError, match='Archive destination.*(symlink|reparse)'):
            source_archive.archive(output, root)

    assert source_archive._is_link(alias)
    assert sentinel.read_bytes() == b'private sentinel must not be overwritten'
    assert sorted(path.name for path in private.iterdir()) == ['source.zip']
    if placement == 'cancelled-parent':
        assert (tmp_path / 'source.zip').read_bytes() == b'previous approved archive'
    assert not list(tmp_path.glob('.vox-source-*'))


@pytest.mark.parametrize('placement', ['root', 'ancestor', 'cancelled-ancestor'])
def test_source_root_alias_is_rejected_before_resolve_or_write(
    tmp_path, monkeypatch, directory_alias, placement,
):
    actual = tmp_path / 'actual'
    root = source_root(actual)
    private = root / '.audit' / 'private.py'
    private.parent.mkdir()
    private.write_bytes(b'private sentinel must not be published')
    if placement == 'root':
        supplied = directory_alias(tmp_path / 'alias', root)
    else:
        alias = directory_alias(tmp_path / 'alias', actual)
        supplied = alias / 'source'
        if placement == 'cancelled-ancestor':
            supplied = alias / '..' / 'actual' / 'source'
    output = tmp_path / 'source.zip'
    output.write_bytes(b'previous approved archive')

    with monkeypatch.context() as patch:
        _forbid_resolve_and_writes(patch)
        with pytest.raises(ValueError, match='Source root'):
            source_archive.archive(output, supplied)

    assert output.read_bytes() == b'previous approved archive'
    assert private.read_bytes() == b'private sentinel must not be published'
    assert not list(tmp_path.glob('.vox-source-*'))


def test_uninspectable_destination_parent_fails_before_resolve_or_write(tmp_path, monkeypatch):
    root = source_root(tmp_path)
    parent = tmp_path / 'destination'
    parent.mkdir()
    output = parent / 'source.zip'
    output.write_bytes(b'previous approved archive')
    original = Path.lstat

    def inspect(path, *args, **kwargs):
        if path == parent:
            raise PermissionError('cannot inspect destination parent')
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'lstat', inspect)
        _forbid_resolve_and_writes(patch)
        with pytest.raises(ValueError, match='Cannot inspect archive destination'):
            source_archive.archive(output, root)

    assert output.read_bytes() == b'previous approved archive'
    assert not list(parent.glob('.vox-source-*'))
