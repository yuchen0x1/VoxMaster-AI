"""Only reviewed Git inputs belong in release archives and redistributed manuals."""
import importlib.util
from pathlib import Path
import os
import subprocess
from zipfile import ZipFile

import pytest

from scripts import source_archive


def git_checkout(tmp_path):
    root = tmp_path / 'checkout'
    root.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True, capture_output=True)
    (root / 'LICENSE').write_text('public test license', encoding='utf-8')
    (root / 'app.py').write_text('"""Public application."""', encoding='utf-8')
    (root / 'docs').mkdir()
    (root / 'docs/manual.md').write_text('Public manual', encoding='utf-8')
    (root / '.gitignore').write_text('docs/private.txt\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '--', 'LICENSE', 'app.py',
                    'docs/manual.md', '.gitignore'], check=True, capture_output=True)
    return root


def test_git_archive_excludes_untracked_and_ignored_documents(tmp_path):
    root = git_checkout(tmp_path)
    (root / 'docs/operator-notes.md').write_text('local-only operator notes', encoding='utf-8')
    (root / 'docs/private.txt').write_text('local-only private metadata', encoding='utf-8')
    destination = tmp_path / 'release.zip'
    source_archive.archive(destination, root)
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'app.py', 'docs/manual.md', '.gitignore'}
    assert (root / 'docs/operator-notes.md').read_text('utf-8') == 'local-only operator notes'


def test_git_scope_query_failure_does_not_fall_back_to_filesystem(tmp_path, monkeypatch):
    root = git_checkout(tmp_path)

    def failed_scope(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['git', 'ls-files'])

    monkeypatch.setattr(subprocess, 'run', failed_scope)
    with pytest.raises(subprocess.CalledProcessError):
        list(source_archive.source_files(root))


def load_stage(root, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'packaging/stage.py'
    spec = importlib.util.spec_from_file_location('vox_test_stage', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'DIST', root / 'dist')
    monkeypatch.setattr(module, 'INFO', root / 'dist/ThirdParty')
    module.INFO.mkdir(parents=True)
    return module


def add_shipping_documents(root):
    for name in ['README.md', 'CHANGELOG.md', 'docs/THIRD_PARTY.md']:
        (root / name).write_text('Public shipping document', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '--', 'README.md', 'CHANGELOG.md',
                    'docs/THIRD_PARTY.md'], check=True, capture_output=True)


def test_staged_documents_share_the_git_allowlist(tmp_path, monkeypatch):
    root = git_checkout(tmp_path)
    add_shipping_documents(root)
    (root / 'docs/operator-notes.md').write_text('local-only notes', encoding='utf-8')
    stage = load_stage(root, monkeypatch)
    stage.copy_documents()
    assert (stage.DIST / 'docs/manual.md').read_text('utf-8') == 'Public manual'
    assert not (stage.DIST / 'docs/operator-notes.md').exists()
    assert (stage.INFO / 'VoxMaster-AI-LICENSE.txt').read_text('utf-8') == 'public test license'


def test_stale_staged_document_aborts_without_removing_local_data(tmp_path, monkeypatch):
    root = git_checkout(tmp_path)
    add_shipping_documents(root)
    stage = load_stage(root, monkeypatch)
    stale = stage.DIST / 'docs/old-notes.txt'
    stale.parent.mkdir()
    stale.write_text('preserve and refuse to publish', encoding='utf-8')
    with pytest.raises(ValueError, match='Stale'):
        stage.copy_documents()
    assert stale.read_text('utf-8') == 'preserve and refuse to publish'
    assert not (stage.DIST / 'README.md').exists()


def test_archive_rejects_directory_links_escaping_source_tree(tmp_path):
    root = tmp_path / 'source'
    outside = tmp_path / 'private'
    (root / 'docs').mkdir(parents=True)
    outside.mkdir()
    (root / 'LICENSE').write_text('public test license', encoding='utf-8')
    (outside / 'private.md').write_text('private linked metadata', encoding='utf-8')
    link = root / 'docs/linked'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip('Directory junctions are unavailable on this volume.')
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        files = dict((name, path) for path, name in source_archive.source_files(root))
        assert set(files) == {'LICENSE'}
    finally:
        if os.name == 'nt':
            link.rmdir()
        else:
            link.unlink()
    assert (outside / 'private.md').read_text('utf-8') == 'private linked metadata'


def test_git_archive_rejects_unstaged_reviewed_change(tmp_path):
    root = git_checkout(tmp_path)
    (root / 'app.py').write_text('unstaged source change', encoding='utf-8')
    with pytest.raises(ValueError, match='staged source archive inputs'):
        list(source_archive.source_files(root))


def test_git_archive_requires_tracked_license(tmp_path):
    root = git_checkout(tmp_path)
    subprocess.run(['git', '-C', str(root), 'rm', '--cached', '--', 'LICENSE'],
                   check=True, capture_output=True)
    with pytest.raises(ValueError, match='tracked source input'):
        list(source_archive.source_files(root))


def test_private_directory_filter_is_case_insensitive(tmp_path):
    root = git_checkout(tmp_path)
    private = root / 'docs' / '.AuDiT'
    private.mkdir()
    (private / 'local.txt').write_text('local-only evidence', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '--', 'docs/.AuDiT/local.txt'],
                   check=True, capture_output=True)
    assert all(not name.casefold().startswith('docs/.audit/')
               for _, name in source_archive.source_files(root))


def test_staged_documents_reject_destination_directory_link(tmp_path, monkeypatch):
    root = git_checkout(tmp_path)
    add_shipping_documents(root)
    stage = load_stage(root, monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = stage.DIST / 'docs'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True)
        if result.returncode:
            pytest.skip('Directory junctions are unavailable on this volume.')
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match='escapes staging directory|symlink or junction'):
            stage.copy_documents()
    finally:
        if os.name == 'nt':
            link.rmdir()
        else:
            link.unlink()
    assert not list(outside.iterdir())
