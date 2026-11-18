"""Synchronize or verify all embedded product versions."""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--set', dest='version')
    parser.add_argument('--tag')
    args = parser.parse_args()
    init = ROOT / 'vox/__init__.py'
    current = re.search(r'__version__ = "([^"]+)"', init.read_text('utf-8'))[1]
    version = args.version or current
    if not re.fullmatch(r'0|[1-9]\d*', version.split('.')[0]) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a three-part numeric product version')
    files = {
        init: (f'__version__ = "{current}"', f'__version__ = "{version}"'),
        ROOT / 'packaging/VoxMasterAI.iss': (r'#define ProductVersion "[^"]+"', f'#define ProductVersion "{version}"'),
    }
    v = ROOT / 'packaging/version.txt'
    text = v.read_text('utf-8')
    expected = re.sub(r'(filevers|prodvers)=\([\d,]+\)', lambda m: m[1] + '=(' + version.replace('.', ',') + ',0)', text)
    expected = re.sub(r'(StringStruct\("(?:FileVersion|ProductVersion)",")[^"]+', r'\g<1>' + version, expected)
    for path, (pattern, replacement) in files.items():
        old = path.read_text('utf-8')
        new = re.sub(pattern, replacement, old)
        if args.version:
            path.write_text(new, 'utf-8', newline='\n')
        elif new != old:
            raise ValueError('Version mismatch: ' + str(path))
    if args.version:
        v.write_text(expected, 'utf-8', newline='\n')
    elif text != expected:
        raise ValueError('Windows resource version mismatch')
    if args.tag and args.tag != 'v' + version:
        raise ValueError('Tag does not match product version')
    print(version)
    return 0


if __name__ == '__main__':
    sys.exit(main())
