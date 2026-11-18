"""Prepare versioned assets and an Ed25519-authenticated update manifest."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vox import __version__
from vox.updating import RELEASES, verify_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    key_bytes = args.key_file.read_bytes() if args.key_file else os.environ['UPDATE_SIGNING_KEY'].encode()
    key = serialization.load_pem_private_key(key_bytes, password=None)
    out = ROOT / 'dist/release'
    out.mkdir(parents=True, exist_ok=True)
    assets = {}
    for source, platform, kind, ext in [
        ('VoxMasterAI-Setup.exe', 'Windows-x64', 'Setup', 'exe'),
        ('VoxMasterAI-Portable.zip', 'Windows-x64', 'Portable', 'zip'),
        ('VoxMasterAI-Source.zip', 'Source', 'Kit', 'zip'),
    ]:
        dest = out / f'VoxMasterAI-{__version__}-{platform}-{kind}.{ext}'
        shutil.copy2(ROOT / 'dist' / source, dest)
        data = dict(name=dest.name, size=dest.stat().st_size,
                    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                    url=RELEASES + '/download/v' + __version__ + '/' + dest.name)
        if platform == 'Windows-x64':
            assets['windows-x64-' + kind.lower()] = data
    shutil.copy2(ROOT / 'dist/Qt-6.12.0-Corresponding-Sources.zip', out)
    notes = (ROOT / 'docs/releases/release-notes.md').read_text('utf-8').split('\n## ', 2)[1]
    manifest = dict(schema=1, version=__version__, minimum_version='0.1.1',
                    published_at=dt.datetime.now(dt.timezone.utc).isoformat(), notes=notes,
                    assets=assets)
    body = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    signature = base64.b64encode(key.sign(body))
    verify_manifest(body, signature)  # Fail closed if CI secret does not match embedded key.
    (out / 'update.json').write_bytes(body)
    (out / 'update.json.sig').write_bytes(signature)
    sums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                   for p in sorted(out.iterdir()) if p.is_file() and p.name != 'SHA256SUMS.txt')
    (out / 'SHA256SUMS.txt').write_text(sums, 'ascii')
    print('Signed release prepared: ' + __version__)


if __name__ == '__main__':
    main()
