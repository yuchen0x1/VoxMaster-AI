"""Read the public update channel; optionally download and verify its installer."""
import argparse
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vox import updating


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--download', action='store_true')
    args = p.parse_args()
    data = updating.check_release()
    for asset in data['assets'].values():
        with updating.response(asset['url']) as r:
            if r.headers.get('Content-Length') and int(r.headers['Content-Length']) != asset['size']:
                raise ValueError('Published asset length mismatch')
        print(asset['name'], 'link PASS')
    if args.download:
        with tempfile.TemporaryDirectory() as folder:
            asset = data['assets']['windows-x64-setup']
            updating.download(asset, threading.Event(), lambda *a: None, folder)
            print('Complete installer download and SHA-256 PASS')
    print('Public manifest Ed25519 PASS', data['version'])


if __name__ == '__main__':
    main()
