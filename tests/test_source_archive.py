"""Release archives must retain the app license, not private media or model caches."""
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest

from scripts import source_archive

ROOT = Path(__file__).resolve().parents[1]


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
