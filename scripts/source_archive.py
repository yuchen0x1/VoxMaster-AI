"""Build a source archive without private media, cached models or local build state."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SCOPES = (
    'app.py', 'vox', 'scripts', 'packaging', 'tests', 'docs', '.github',
    'requirements.txt', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'SECURITY.md', 'CODE_OF_CONDUCT.md', 'LICENSE', '.gitignore',
)
PRIVATE = {'__pycache__', '.pytest_cache', '.ruff_cache', '.audit', '.agents', '.venv',
           'real_audio', 'node_modules'}
MEDIA = {'.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.aiff', '.aif', '.opus',
         '.mp4', '.webm', '.mov', '.voxproj'}
WEIGHTS = {'.onnx', '.pt', '.pth', '.ckpt', '.safetensors'}
FIXTURE = 'tests/fixtures/fleurs-mandarin.wav'
FIXTURE_SHA = 'a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b'
_REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _is_link(path):
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & _REPARSE_POINT)
    except OSError:
        return True


def source_files(root):
    root = Path(root).resolve()
    license_path = root / 'LICENSE'
    if (
        not license_path.is_file()
        or _is_link(license_path)
        or license_path.resolve() != license_path.absolute()
    ):
        raise ValueError('Root LICENSE must be a regular file in the source archive')
    if (root / '.git').exists():
        # Git checkouts include reviewed/staged paths only. A failed query must
        # never silently fall back to shipping local notes or ignored state.
        clean = subprocess.run(
            ['git', '-C', str(root), 'diff', '--quiet', '--', *SCOPES],
            check=False, capture_output=True,
        )
        if clean.returncode:
            if clean.returncode == 1:
                raise ValueError('Working tree differs from the staged source archive inputs')
            raise subprocess.CalledProcessError(clean.returncode, clean.args)
        result = subprocess.run(
            ['git', '-C', str(root), 'ls-files', '--cached', '-z', '--', *SCOPES],
            check=True, capture_output=True, text=True, encoding='utf-8',
        )
        names = [name for name in result.stdout.split('\0') if name]
        if 'LICENSE' not in names:
            raise ValueError('Root LICENSE must be a tracked source input')
        paths = [root / name for name in names]
    else:
        # A distributed source kit has no .git directory and remains rebuildable.
        paths = []
        for scope in SCOPES:
            base = root / scope
            paths.extend(base.rglob('*') if base.is_dir() else [base])
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if not path.is_file() or any(part.casefold() in PRIVATE for part in relative.parts):
            continue
        if not path.resolve().is_relative_to(root):
            continue
        if any(_is_link(parent) for parent in (path, *path.parents) if parent != root):
            continue
        if path.suffix.lower() in MEDIA | WEIGHTS:
            if relative.as_posix() != FIXTURE:
                continue
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != FIXTURE_SHA:
                raise ValueError('Licensed FLEURS fixture was replaced; refusing to package audio')
        yield path, relative.as_posix()


def archive(destination, root=ROOT):
    destination = Path(destination).resolve()
    if destination.suffix.lower() != '.zip':
        raise ValueError('Source archive must use a .zip extension')
    files = list(source_files(root))
    if any(destination == path.resolve() for path, _ in files):
        raise ValueError('Archive must not replace any source file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.vox-source-', suffix='.zip', dir=destination.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED, compresslevel=6) as output:
            for path, name in files:
                output.write(path, name)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(f'Source archive: {archive(args.destination)} files; private media and models excluded')


if __name__ == '__main__':
    main()
