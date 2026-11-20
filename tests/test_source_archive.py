"""Release archives must retain the app license, not private media or model caches."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import source_archive

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'packaging/upstream/mingw-w64-lame-3.100-3.src.tar.zst'


def _write(path, content=b'test'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_archive_filters_private_media_and_keeps_attributed_fixture(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    shutil.copy2(ROOT / 'LICENSE', root / 'LICENSE')
    fixture = root / source_archive.FIXTURE
    fixture.parent.mkdir(parents=True)
    shutil.copy2(ROOT / source_archive.FIXTURE, fixture)
    (root / 'vox').mkdir()
    (root / 'vox/test.py').write_text('"""Source file."""', encoding='utf-8')
    (root / 'tests/assets/real_audio').mkdir(parents=True)
    (root / 'tests/assets/real_audio/private.json').write_text('private', encoding='utf-8')
    for suffix in source_archive.MEDIA | source_archive.WEIGHTS:
        (root / 'tests' / ('private' + suffix)).write_bytes(b'private')
    destination = tmp_path / 'source.zip'
    assert source_archive.archive(destination, root) == 3
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'vox/test.py', source_archive.FIXTURE}
        assert archive.read('LICENSE') == (ROOT / 'LICENSE').read_bytes()


def test_replaced_fixture_aborts_without_overwriting_existing_archive(tmp_path):
    (tmp_path / 'LICENSE').write_text('test license', encoding='utf-8')
    fixture = tmp_path / source_archive.FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b'a user song masquerading as the licensed fixture')
    output = tmp_path / 'source.zip'
    output.write_bytes(b'previous archive')
    with pytest.raises(ValueError, match='fixture was replaced'):
        source_archive.archive(output, tmp_path)
    assert output.read_bytes() == b'previous archive'
    assert not list(tmp_path.glob('.vox-source-*'))


def test_license_is_required_and_non_zip_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='LICENSE'):
        source_archive.archive(tmp_path / 'source.zip', tmp_path)
    with pytest.raises(ValueError, match='.zip'):
        source_archive.archive(tmp_path / 'LICENSE', tmp_path)


def test_scope_allowlist_drops_unapproved_files_but_keeps_build_and_license_inputs(tmp_path):
    root = tmp_path / 'source'
    _write(root / 'LICENSE', b'MIT license')
    _write(root / 'README.md')
    _write(root / 'app.py')
    _write(root / 'vox' / 'core.py')
    _write(root / 'scripts' / 'build.ps1')
    _write(root / 'scripts' / 'release.py')
    _write(root / 'scripts' / 'unknown.bin')
    _write(root / 'packaging' / 'VoxMasterAI.spec')
    _write(root / 'packaging' / 'VoxMasterAI.iss')
    _write(root / 'packaging' / 'build-codecs.sh')
    _write(root / 'packaging' / 'VoxMasterAI.ico')
    _write(root / 'packaging' / 'version.txt')
    _write(root / 'packaging' / 'licenses' / 'ThirdPartyNotices.txt')
    upstream = root / UPSTREAM
    upstream.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / UPSTREAM, upstream)
    _write(root / 'tests' / 'test_core.py')
    _write(root / 'tests' / 'fixtures' / 'README.md')
    _write(root / 'tests' / 'mc_corpus' / 'README.md')
    catalog = root / 'tests' / 'mc_corpus' / 'sources.json'
    shutil.copy2(ROOT / 'tests' / 'mc_corpus' / 'sources.json', catalog)
    _write(root / 'docs' / 'ARCHITECTURE.md')
    _write(root / 'docs' / 'workstation.png')
    _write(root / '.github' / 'workflows' / 'release.yml')
    _write(root / '.github' / 'CODEOWNERS')

    sentinels = (
        'tests/private.caf', 'tests/private.wma', 'tests/private.raw', 'tests/private.pcm',
        'tests/private.pem', 'tests/private.key', 'tests/private.p12', 'tests/private.pfx',
        'tests/.env', 'tests/private.unknown', 'tests/private.json',
        'docs/evidence-020/pytest.txt',
        'docs/evidence-020/crash.xml', 'docs/evidence-020/private.json',
        'docs/evidence-020/private.jsonl', 'packaging/private.caf',
    )
    for name in sentinels:
        _write(root / name, b'sentinel must not ship')

    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        names = set(archive.namelist())

    expected = {
        'LICENSE', 'README.md', 'app.py', 'vox/core.py', 'scripts/build.ps1',
        'scripts/release.py', 'packaging/VoxMasterAI.spec', 'packaging/VoxMasterAI.iss',
        'packaging/build-codecs.sh', 'packaging/VoxMasterAI.ico', 'packaging/version.txt',
        'packaging/licenses/ThirdPartyNotices.txt', UPSTREAM, 'tests/test_core.py',
        'tests/fixtures/README.md', 'tests/mc_corpus/README.md',
        'tests/mc_corpus/sources.json', 'docs/ARCHITECTURE.md', 'docs/workstation.png',
        '.github/workflows/release.yml', '.github/CODEOWNERS',
    }
    assert names == expected
    assert not names.intersection(sentinels)


def test_catalog_retains_public_sources_and_anonymizes_only_local_filenames(tmp_path):
    root = tmp_path / 'source'
    _write(root / 'LICENSE')
    relative = Path('tests/mc_corpus/sources.json')
    catalog = root / relative
    catalog.parent.mkdir(parents=True)
    original = (ROOT / relative).read_bytes()
    catalog.write_bytes(original)
    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        packed = json.loads(archive.read(relative.as_posix()))
    reviewed = json.loads(original)
    assert len(packed) == len(reviewed)
    for before, after in zip(reviewed, packed, strict=True):
        if before['location'] == 'local':
            assert after['file'] == before['id'] + Path(before['file']).suffix
            assert {k: v for k, v in after.items() if k != 'file'} == {
                k: v for k, v in before.items() if k != 'file'
            }
        else:
            assert after == before
    assert catalog.read_bytes() == original
    assert hashlib.sha256(original.replace(b'\r\n', b'\n')).hexdigest() in {
        source_archive.CATALOG_SHA, source_archive.PUBLIC_CATALOG_SHA,
    }
    # Repacking the distributed source must remain supported and byte-stable.
    catalog.write_bytes((json.dumps(packed, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert json.loads(archive.read(relative.as_posix())) == packed


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'], ids=['LF', 'CRLF'])
def test_catalog_line_endings_do_not_change_reviewed_content(tmp_path, newline):
    canonical = (ROOT / source_archive.CATALOG).read_bytes().replace(b'\r\n', b'\n')
    path = tmp_path / 'sources.json'
    path.write_bytes(canonical.replace(b'\n', newline))
    assert source_archive._public_catalog(path) == canonical


def test_reviewed_local_catalog_filename_is_not_distributed(tmp_path, monkeypatch):
    _write(tmp_path / 'LICENSE')
    relative = 'tests/mc_corpus/sources.json'
    original = b'[{"id":"MC01","location":"local","file":"private-sentinel.mp3","private_digest_required":true}]'
    _write(tmp_path / relative, original)
    monkeypatch.setattr(source_archive, 'CATALOG_SHA', hashlib.sha256(original).hexdigest())
    output = tmp_path / 'source.zip'
    source_archive.archive(output, tmp_path)
    with ZipFile(output) as archive:
        packed = archive.read(relative)
    assert b'private-sentinel' not in packed
    assert json.loads(packed)[0]['file'] == 'MC01.mp3'
    assert (tmp_path / relative).read_bytes() == original


def test_changed_catalog_aborts_without_replacing_previous_archive(tmp_path):
    _write(tmp_path / 'LICENSE')
    catalog = tmp_path / 'tests/mc_corpus/sources.json'
    _write(catalog, b'[{"location":"local","file":"private-sentinel.mp3"}]')
    output = tmp_path / 'source.zip'
    output.write_bytes(b'previous archive')
    with pytest.raises(ValueError, match='catalog.*changed'):
        source_archive.archive(output, tmp_path)
    assert output.read_bytes() == b'previous archive'
    assert not list(tmp_path.glob('.vox-source-*'))


def test_replaced_upstream_source_aborts_without_replacing_previous_archive(tmp_path):
    _write(tmp_path / 'LICENSE')
    _write(tmp_path / UPSTREAM, b'not the reviewed corresponding sources')
    output = tmp_path / 'source.zip'
    output.write_bytes(b'previous archive')
    with pytest.raises(ValueError, match='upstream.*changed'):
        source_archive.archive(output, tmp_path)
    assert output.read_bytes() == b'previous archive'


def test_source_archive_skips_symlinked_files_and_directories(tmp_path):
    root = tmp_path / 'source'
    _write(root / 'LICENSE')
    _write(root / 'scripts' / 'real.py')
    outside = tmp_path / 'outside.py'
    outside.write_text('must not be archived', encoding='utf-8')
    try:
        (root / 'scripts' / 'linked.py').symlink_to(outside)
        (root / 'scripts' / 'linked-dir').symlink_to(root / 'scripts', target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink creation is unavailable: {exc}')

    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'scripts/real.py'}


def test_symlinked_root_license_is_rejected(tmp_path):
    root = tmp_path / 'source'
    outside = tmp_path / 'outside-license'
    outside.write_text('not the repository license', encoding='utf-8')
    try:
        (root / 'LICENSE').parent.mkdir(parents=True)
        (root / 'LICENSE').symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink creation is unavailable: {exc}')

    with pytest.raises(ValueError, match='LICENSE'):
        source_archive.archive(tmp_path / 'source.zip', root)


@pytest.mark.skipif(os.name != 'nt', reason='junctions are Windows-specific')
def test_junction_to_outside_root_is_not_archived(tmp_path):
    root = tmp_path / 'source'
    _write(root / 'LICENSE')
    outside = tmp_path / 'outside-dir'
    _write(outside / 'outside.py')
    junction = root / 'scripts' / 'junction'
    junction.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)],
        check=False, capture_output=True,
    )
    if result.returncode:
        pytest.skip(f'junction creation is unavailable: {result.stderr.strip()}')

    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE'}


@pytest.mark.skipif(os.name != 'nt', reason='junctions are Windows-specific')
@pytest.mark.parametrize('private_directory', ['.AuDiT', 'real_audio'])
def test_junction_to_private_directory_inside_root_is_not_archived(tmp_path, private_directory):
    root = tmp_path / 'source'
    _write(root / 'LICENSE')
    _write(root / 'scripts' / 'public.py')
    private = root / private_directory
    _write(private / 'private.py', b'private sentinel must not ship')
    junction = root / 'scripts' / 'alias'
    result = subprocess.run(
        ['cmd.exe', '/c', 'mklink', '/J', str(junction), str(private)],
        check=False, capture_output=True, timeout=30,
    )
    if result.returncode:
        pytest.skip(f'junction creation is unavailable: {result.stderr.strip()}')

    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'scripts/public.py'}


def test_unexpected_extension_is_not_archived_from_every_source_scope(tmp_path):
    root = tmp_path / 'source'
    _write(root / 'LICENSE')
    for scope in ('vox', 'scripts', 'packaging', 'tests', 'docs', '.github'):
        _write(root / scope / 'payload.unknown', b'not an approved source type')
    _write(root / 'tests' / '.PYTEST_CACHE' / 'private.py')
    _write(root / 'docs' / '.AUDIT' / 'private.md')
    _write(root / 'scripts' / 'expected.py')
    output = tmp_path / 'source.zip'
    source_archive.archive(output, root)
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {'LICENSE', 'scripts/expected.py'}
