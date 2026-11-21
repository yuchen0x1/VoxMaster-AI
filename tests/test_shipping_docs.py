"""Shipping docs are an explicit, offline-usable subset, not raw QA evidence."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('shipping_docs', ROOT / 'packaging/shipping_docs.py')
shipping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shipping)
MANAGED_TARGETS = ('docs', 'README.md', 'LICENSE', 'CHANGELOG.md',
                   'ThirdParty/THIRD_PARTY.md', 'ThirdParty/VoxMaster-AI-LICENSE.txt')


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    (root / 'docs').mkdir(parents=True)
    (root / 'LICENSE').write_text('MIT licensed application', 'utf-8')
    (root / 'README.md').write_text('Developer overview', 'utf-8')
    (root / 'CHANGELOG.md').write_text('Developer history', 'utf-8')
    for name in shipping.DOCUMENTS:
        (root / 'docs' / name).write_text('# User manual\n', 'utf-8')
    for name in shipping.IMAGES:
        (root / 'docs' / name).write_bytes(b'reviewed image')
    return root


@pytest.fixture
def previous_package(tmp_path):
    destination = tmp_path / 'package'
    files = {'docs/old.txt': b'only previous docs copy',
             'docs/nested/keep.bin': b'previous nested document',
             'ThirdParty/retain-license.txt': b'unmanaged license',
             'runtime/keep.bin': b'unmanaged application file'}
    files.update({relative: ('only previous copy of ' + relative).encode('utf-8')
                  for relative in MANAGED_TARGETS if relative != 'docs'})
    for relative, data in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return destination


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


def _directory_link(link, target):
    if sys.platform == 'win32':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True)
        assert result.returncode == 0, (result.stdout, result.stderr)
    else:
        link.symlink_to(target, target_is_directory=True)


def test_unknown_evidence_and_old_staging_do_not_ship(source, tmp_path):
    for name in ('trace.json', 'run.jsonl', 'local.txt', 'private.csv', 'internal.md', 'private.png'):
        (source / 'docs' / name).write_text('private sentinel', 'utf-8')
    (source / 'README.md').write_text('private sentinel', 'utf-8')
    (source / 'CHANGELOG.md').write_text('private sentinel', 'utf-8')
    destination = tmp_path / 'package'
    (destination / 'docs/old').mkdir(parents=True)
    (destination / 'docs/old/private.json').write_text('private sentinel', 'utf-8')
    (destination / 'ThirdParty').mkdir()
    (destination / 'ThirdParty/retain-license.txt').write_bytes(b'copyright')
    (destination / 'CHANGELOG.md').write_text('private sentinel', 'utf-8')
    shipping.copy_documents(source, destination)
    assert set(snapshot(destination / 'docs')) == {*shipping.DOCUMENTS, *shipping.IMAGES, 'INDEX.md'}
    assert b'private sentinel' not in b'\n'.join(snapshot(destination).values())
    assert (destination / 'ThirdParty/retain-license.txt').read_bytes() == b'copyright'
    assert (destination / 'LICENSE').read_bytes() == (source / 'LICENSE').read_bytes()
    assert (destination / 'ThirdParty/VoxMaster-AI-LICENSE.txt').read_bytes() == (source / 'LICENSE').read_bytes()
    assert not list(destination.glob('.vox-docs-*'))


def test_links_keep_local_manuals_and_move_research_online(source, tmp_path):
    (source / 'docs/THIRD_PARTY.md').write_text(
        '[Models](MODELS.md#terms) [License](../LICENSE) [Evidence](evidence/run.json)\n', 'utf-8')
    destination = tmp_path / 'package'
    shipping.copy_documents(source, destination)
    notice = (destination / 'ThirdParty/THIRD_PARTY.md').read_text('utf-8')
    assert '(../docs/MODELS.md#terms)' in notice
    assert '(../LICENSE)' in notice
    assert shipping.SOURCE_URL + 'docs/evidence/run.json' in notice
    assert '(MODELS.md#terms)' in (destination / 'docs/THIRD_PARTY.md').read_text('utf-8')


@pytest.mark.parametrize('link', ['file:///C:/private.txt', 'C:/private.txt', '//server/share',
                                  '../../../outside.md', '%2e%2e/%2e%2e/private.md',
                                  'httpsomething:private', 'folder%5csecret.md', '/absolute.md',
                                  'javascript:alert', 'data:text/plain,secret'])
def test_unsafe_links_fail_before_replacing_existing_documents(source, tmp_path, link):
    (source / 'docs/MANUAL.md').write_text('[link](' + link + ')', 'utf-8')
    destination = tmp_path / 'package'
    (destination / 'docs').mkdir(parents=True)
    (destination / 'docs/keep.txt').write_bytes(b'old build')
    before = snapshot(destination)
    with pytest.raises(ValueError):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before


def test_missing_required_document_preserves_existing_staging(source, tmp_path):
    (source / 'docs/MODELS.md').unlink()
    destination = tmp_path / 'package'
    destination.mkdir()
    (destination / 'keep.bin').write_bytes(b'preserve')
    before = snapshot(destination)
    with pytest.raises(ValueError, match='missing or linked'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before


def test_failed_docs_publish_restores_previous_directory(source, tmp_path, monkeypatch):
    destination = tmp_path / 'package'
    (destination / 'docs').mkdir(parents=True)
    (destination / 'docs/old.txt').write_bytes(b'old build')
    before = snapshot(destination)
    replace = shipping.os.replace

    def fail_publish(src, dst):
        if Path(src).name == 'docs' and Path(src).parent.name == 'prepared':
            raise OSError('injected publish failure')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', fail_publish)
    with pytest.raises(OSError, match='injected'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before


@pytest.mark.parametrize('relative', MANAGED_TARGETS)
@pytest.mark.parametrize('interrupt_type', [KeyboardInterrupt, SystemExit])
def test_base_exception_after_old_move_keeps_recovery_transaction(
        source, previous_package, tmp_path, monkeypatch, relative, interrupt_type):
    destination = previous_package
    before = snapshot(destination)
    replace = shipping.os.replace

    def interrupt_after_move(src, dst):
        if Path(src) == destination / relative and 'previous' in Path(dst).parts:
            replace(src, dst)
            # The wrapper never returns, so the old_moved state is still false.
            raise interrupt_type('injected interrupt after backup move')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', interrupt_after_move)
    with pytest.raises(interrupt_type, match='after backup move'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before
    backups = list(tmp_path.glob('.package-docs-*'))
    assert len(backups) == 1
    # Successful rollback moves the old bytes back, not into a second copy.
    assert snapshot(backups[0] / 'previous') == {}
    monkeypatch.setattr(shipping.os, 'replace', replace)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert backups[0].is_dir()
    assert snapshot(destination) == before


@pytest.mark.parametrize('relative', MANAGED_TARGETS)
@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('error_type', [OSError, KeyboardInterrupt, SystemExit])
def test_error_after_new_publish_restores_previous_state(
        source, previous_package, tmp_path, monkeypatch, relative, existing, error_type):
    destination = previous_package if existing else tmp_path / 'fresh'
    if not existing:
        destination.mkdir()
        (destination / 'unowned.bin').write_bytes(b'unmanaged application file')
    before = snapshot(destination)
    replace = shipping.os.replace

    def interrupt_after_publish(src, dst):
        result = replace(src, dst)
        if 'prepared' in Path(src).parts and Path(dst) == destination / relative:
            raise error_type('injected error after new publish')
        return result

    monkeypatch.setattr(shipping.os, 'replace', interrupt_after_publish)
    with pytest.raises(error_type, match='after new publish'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before
    if not existing:
        assert not (destination / 'ThirdParty').exists()
    backups = list(tmp_path.glob('.' + destination.name + '-docs-*'))
    if error_type is OSError:
        assert not backups
    else:
        assert len(backups) == 1
        assert snapshot(backups[0] / 'previous') == {}
        monkeypatch.setattr(shipping.os, 'replace', replace)
        with pytest.raises(ValueError, match='Unresolved'):
            shipping.copy_documents(source, destination)
        assert snapshot(destination) == before


def test_real_document_subset_has_no_broken_offline_links(tmp_path):
    destination = tmp_path / 'package'
    shipping.copy_documents(ROOT, destination)
    for path in destination.rglob('*.md'):
        text = path.read_text('utf-8')
        for match in shipping.LINK.finditer(text):
            parsed = urlsplit(match[2])
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            assert resolved.is_relative_to(destination.resolve()), (path, match[2])
            assert resolved.is_file(), (path, match[2])
    before = snapshot(destination)
    shipping.copy_documents(ROOT, destination)
    assert snapshot(destination) == before


def test_stage_entrypoint_uses_reviewed_subset(source, tmp_path, monkeypatch):
    # stage.py imports Windows-only pefile, but docs staging is platform neutral.
    monkeypatch.setitem(sys.modules, 'shipping_docs', shipping)
    monkeypatch.setitem(sys.modules, 'pefile', object())
    spec = importlib.util.spec_from_file_location('package_stage', ROOT / 'packaging/stage.py')
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    destination = tmp_path / 'package'
    monkeypatch.setattr(stage, 'ROOT', source)
    monkeypatch.setattr(stage, 'DIST', destination)
    monkeypatch.setattr(stage, 'INFO', destination / 'ThirdParty')
    (destination / 'ThirdParty').mkdir(parents=True)
    (source / 'docs/private.json').write_text('private sentinel', 'utf-8')
    stage.copy_documents()
    assert not (destination / 'docs/private.json').exists()
    assert (destination / 'docs/INDEX.md').is_file()
    assert set(snapshot(destination / 'docs')) == {*shipping.DOCUMENTS, *shipping.IMAGES, 'INDEX.md'}


@pytest.mark.parametrize('where', ['root', 'ancestor'])
@pytest.mark.parametrize('dangling', [False, True])
def test_linked_source_root_or_ancestor_is_rejected(source, tmp_path, monkeypatch, where, dangling):
    outside = tmp_path / 'external'
    outside.mkdir()
    source = source.rename(outside / 'source')
    destination = tmp_path / 'package'
    (destination / 'ThirdParty').mkdir(parents=True)
    (destination / 'ThirdParty/retain-license.txt').write_bytes(b'unmanaged license')
    source_before, destination_before = snapshot(source), snapshot(destination)
    link = tmp_path / 'source-alias'
    _directory_link(link, source if where == 'root' else outside)
    supplied_root = link if where == 'root' else link / source.name
    resolve = Path.resolve

    def reject_alias_resolution(path, *args, **kwargs):
        assert path != supplied_root, 'Reject the source alias before resolving it'
        return resolve(path, *args, **kwargs)

    try:
        # A real junction on Windows, including a target that goes missing.
        if dangling:
            outside = outside.rename(tmp_path / 'relocated')
            source = outside / source.name
            assert not supplied_root.exists()
            assert os.path.lexists(link)
        else:
            assert supplied_root.resolve() == source.resolve()
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'resolve', reject_alias_resolution)
            with pytest.raises(ValueError, match='source.*linked'):
                shipping.copy_documents(supplied_root, destination)
        assert snapshot(source) == source_before
        assert snapshot(destination) == destination_before
        assert not list(tmp_path.glob('.package-docs-*'))
    finally:
        if sys.platform == 'win32':
            os.rmdir(link)
        else:
            link.unlink()


def test_unlinked_source_with_dotdot_is_accepted(source, tmp_path):
    destination = tmp_path / 'package'
    shipping.copy_documents(source / 'docs/..', destination)
    assert (destination / 'docs/MANUAL.md').read_text('utf-8') == (source / 'docs/MANUAL.md').read_text('utf-8')


def test_source_tree_cannot_be_used_as_destination(source):
    before = snapshot(source)
    with pytest.raises(ValueError, match='source tree'):
        shipping.copy_documents(source, source)
    assert snapshot(source) == before


def test_unresolved_backup_inside_destination_blocks_packaging(source, tmp_path):
    destination = tmp_path / 'package'
    (destination / '.vox-docs-old/previous').mkdir(parents=True)
    (destination / '.vox-docs-old/previous/private.json').write_bytes(b'private sentinel')
    before = snapshot(destination)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before


@pytest.mark.parametrize('relative', MANAGED_TARGETS)
def test_any_publish_failure_rolls_back_all_managed_files(source, tmp_path, monkeypatch, relative):
    destination = tmp_path / 'package'
    shipping.copy_documents(source, destination)
    (destination / 'docs/keep.txt').write_bytes(b'previous evidence')
    before = snapshot(destination)
    replace = shipping.os.replace

    def fail_publish(src, dst):
        if 'prepared' in Path(src).parts and Path(dst) == destination / relative:
            raise OSError('injected late failure')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', fail_publish)
    with pytest.raises(OSError, match='injected'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before
    assert not list(tmp_path.glob('.package-docs-*'))


@pytest.mark.parametrize('relative', ['docs', 'ThirdParty/THIRD_PARTY.md'])
@pytest.mark.parametrize('publish_error', [OSError, KeyboardInterrupt])
@pytest.mark.parametrize('rollback_error', [OSError, SystemExit])
def test_failed_rollback_retains_backup_outside_package_and_blocks_retry(
        source, previous_package, tmp_path, monkeypatch, relative, publish_error, rollback_error):
    destination = previous_package
    before = snapshot(destination)
    previous = {name: data for name, data in before.items()
                if name == relative or name.startswith(relative + '/')}
    replace = shipping.os.replace

    def fail_publish_and_rollback(src, dst):
        if ('prepared' in Path(src).parts
                and Path(dst) == destination / MANAGED_TARGETS[-1]):
            replace(src, dst)
            raise publish_error('injected error after last publish')
        if 'previous' in Path(src).parts and Path(dst) == destination / relative:
            raise rollback_error('injected rollback lock')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', fail_publish_and_rollback)
    with pytest.raises(OSError, match='rollback failed') as failure:
        shipping.copy_documents(source, destination)
    assert isinstance(failure.value.__cause__, publish_error)
    backups = list(tmp_path.glob('.package-docs-*'))
    assert len(backups) == 1
    assert str(backups[0]) in str(failure.value)
    # These bytes exist only in previous, not in the source or new payload.
    assert snapshot(backups[0] / 'previous') == previous
    recovered = {name: data for name, data in before.items() if name not in previous}
    assert snapshot(destination) == recovered
    assert not list(destination.glob('.vox-docs-*'))
    monkeypatch.setattr(shipping.os, 'replace', replace)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert snapshot(backups[0] / 'previous') == previous
    assert snapshot(destination) == recovered


@pytest.mark.parametrize('relative', ['docs', 'ThirdParty/THIRD_PARTY.md'])
@pytest.mark.parametrize('rollback_error', [OSError, KeyboardInterrupt])
def test_rollback_move_then_raise_keeps_restored_bytes_and_recovery_folder(
        source, previous_package, tmp_path, monkeypatch, relative, rollback_error):
    destination = previous_package
    before = snapshot(destination)
    replace = shipping.os.replace

    def fail_after_move(src, dst):
        result = replace(src, dst)
        if ('prepared' in Path(src).parts
                and Path(dst) == destination / MANAGED_TARGETS[-1]):
            raise OSError('injected error after last publish')
        if 'previous' in Path(src).parts and Path(dst) == destination / relative:
            raise rollback_error('injected error after restore move')
        return result

    monkeypatch.setattr(shipping.os, 'replace', fail_after_move)
    with pytest.raises(OSError, match='rollback failed'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before
    backups = list(tmp_path.glob('.package-docs-*'))
    assert len(backups) == 1
    assert snapshot(backups[0] / 'previous') == {}
    monkeypatch.setattr(shipping.os, 'replace', replace)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == before


def test_rollback_does_not_recursively_delete_new_unowned_license(source, tmp_path, monkeypatch):
    destination = tmp_path / 'package'
    (destination / 'docs').mkdir(parents=True)
    (destination / 'docs/old.txt').write_bytes(b'only previous docs copy')
    before = snapshot(destination)
    retained = destination / 'ThirdParty/retain-license.txt'
    replace = shipping.os.replace

    def fail_publish(src, dst):
        if 'prepared' in Path(src).parts and Path(dst) == destination / 'docs':
            retained.write_bytes(b'unmanaged license added during publish')
            raise OSError('injected publish failure')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', fail_publish)
    with pytest.raises(OSError, match='rollback failed'):
        shipping.copy_documents(source, destination)
    expected = {**before, 'ThirdParty/retain-license.txt': b'unmanaged license added during publish'}
    assert snapshot(destination) == expected
    backups = list(tmp_path.glob('.package-docs-*'))
    assert len(backups) == 1
    monkeypatch.setattr(shipping.os, 'replace', replace)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert snapshot(destination) == expected


@pytest.mark.parametrize('where', ['source', 'destination', 'ancestor'])
def test_linked_directories_do_not_read_or_overwrite_external_data(source, tmp_path, where):
    outside = tmp_path / 'external'
    outside.mkdir()
    (outside / 'sentinel.txt').write_bytes(b'private sentinel')
    destination = tmp_path / 'package'
    if where == 'source':
        original = source / 'docs'
        original.rename(source / 'docs-original')
        link = original
    elif where == 'destination':
        link = destination
    else:
        link = tmp_path / 'build'
        destination = link / 'VoxMasterAI'
        (outside / 'VoxMasterAI').mkdir()
        (outside / 'VoxMasterAI/sentinel.txt').write_bytes(b'private sentinel')
    before = snapshot(outside)
    _directory_link(link, outside)
    try:
        with pytest.raises(ValueError, match='linked'):
            shipping.copy_documents(source, destination)
        assert snapshot(outside) == before
    finally:
        if sys.platform == 'win32':
            os.rmdir(link)
        else:
            link.unlink()
