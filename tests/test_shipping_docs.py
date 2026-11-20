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


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob('*') if p.is_file()}


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


@pytest.mark.parametrize('relative', ['docs', 'README.md', 'LICENSE', 'CHANGELOG.md',
                                      'ThirdParty/THIRD_PARTY.md', 'ThirdParty/VoxMaster-AI-LICENSE.txt'])
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


def test_failed_rollback_retains_backup_outside_package_and_blocks_retry(source, tmp_path, monkeypatch):
    destination = tmp_path / 'package'
    (destination / 'docs').mkdir(parents=True)
    (destination / 'docs/keep.txt').write_bytes(b'only previous copy')
    replace = shipping.os.replace

    def fail_publish_and_rollback(src, dst):
        if 'prepared' in Path(src).parts or 'previous' in Path(src).parts:
            raise OSError('injected lock')
        return replace(src, dst)

    monkeypatch.setattr(shipping.os, 'replace', fail_publish_and_rollback)
    with pytest.raises(OSError, match='rollback failed'):
        shipping.copy_documents(source, destination)
    backups = list(tmp_path.glob('.package-docs-*'))
    assert len(backups) == 1
    assert (backups[0] / 'previous/docs/keep.txt').read_bytes() == b'only previous copy'
    assert not list(destination.glob('.vox-docs-*'))
    monkeypatch.setattr(shipping.os, 'replace', replace)
    with pytest.raises(ValueError, match='Unresolved'):
        shipping.copy_documents(source, destination)
    assert (backups[0] / 'previous/docs/keep.txt').is_file()


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
    if sys.platform == 'win32':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match='linked'):
            shipping.copy_documents(source, destination)
        assert snapshot(outside) == before
    finally:
        if sys.platform == 'win32':
            os.rmdir(link)
        else:
            link.unlink()
