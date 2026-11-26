"""Prepare versioned assets and an Ed25519-authenticated update manifest."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vox import __version__
from vox.updating import RELEASES, verify_manifest


def release_notes(root):
    text = (Path(root) / 'docs/releases/release-notes.md').read_text('utf-8')
    match = re.search(
        r'(?ms)^## \d+\.\d+\.\d+[^\n]*\n(.*?)(?=^## \d+\.\d+\.\d+[^\n]*\n|\Z)',
        text,
    )
    if match is None:
        raise ValueError('Release notes do not contain a version section')
    return match.group(1).strip()


def prepare_release(root, key):
    root = Path(root)
    out = root / 'dist/release'
    if out.exists() or out.is_symlink():
        raise FileExistsError('Release staging already exists; inspect it before preparing a new release')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vox-release-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'release'
        staging.mkdir()
        assets = {}
        files = []
        for source, platform, kind, ext in [
            ('VoxMasterAI-Setup.exe', 'Windows-x64', 'Setup', 'exe'),
            ('VoxMasterAI-Portable.zip', 'Windows-x64', 'Portable', 'zip'),
            ('VoxMasterAI-Source.zip', 'Source', 'Kit', 'zip'),
        ]:
            dest = staging / f'VoxMasterAI-{__version__}-{platform}-{kind}.{ext}'
            shutil.copy2(root / 'dist' / source, dest)
            files.append(dest)
            data = dict(name=dest.name, size=dest.stat().st_size,
                        sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                        url=RELEASES + '/download/v' + __version__ + '/' + dest.name)
            if platform == 'Windows-x64':
                assets['windows-x64-' + kind.lower()] = data
        qt = staging / 'Qt-6.12.0-Corresponding-Sources.zip'
        shutil.copy2(root / 'dist' / qt.name, qt)
        files.append(qt)
        notes = release_notes(root)
        manifest = dict(schema=1, version=__version__, minimum_version='0.1.1',
                        published_at=dt.datetime.now(dt.timezone.utc).isoformat(), notes=notes,
                        assets=assets)
        body = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
        signature = base64.b64encode(key.sign(body))
        verify_manifest(body, signature)  # Fail closed if the key does not match the embedded key.
        for name, content in [('update.json', body), ('update.json.sig', signature)]:
            path = staging / name
            path.write_bytes(content)
            files.append(path)
        sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                       for p in sorted(files))
        (staging / 'SHA256SUMS.txt').write_text(sums, 'ascii')
        if out.exists() or out.is_symlink():
            raise FileExistsError('Release staging appeared during preparation; no files replaced')
        staging.rename(out)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--notes-only', type=Path)
    args = parser.parse_args()
    if args.notes_only:
        args.notes_only.write_text(release_notes(ROOT), 'utf-8')
        return
    key_bytes = args.key_file.read_bytes() if args.key_file else os.environ['UPDATE_SIGNING_KEY'].encode()
    key = serialization.load_pem_private_key(key_bytes, password=None)
    prepare_release(ROOT, key)
    print('Signed release prepared: ' + __version__)


if __name__ == '__main__':
    main()
