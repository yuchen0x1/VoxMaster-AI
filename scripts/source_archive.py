"""Build a source archive without private media, cached models or local build state."""
import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCOPES = (
    'app.py', 'vox', 'scripts', 'packaging', 'tests', 'docs', '.github',
    'requirements.txt', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'SECURITY.md', 'CODE_OF_CONDUCT.md', 'LICENSE', '.gitignore',
)
PRIVATE = {'__pycache__', '.pytest_cache', '.ruff_cache', '.audit', '.agents', '.venv',
           'real_audio', 'node_modules'}
PRIVATE_CASEFOLDED = frozenset(part.casefold() for part in PRIVATE)
# These names remain available to callers that use them to build test sentinels.
# They are deliberately not used as an inclusion rule: source_files is allowlist-only.
MEDIA = {'.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.aiff', '.aif', '.opus',
         '.mp4', '.webm', '.mov', '.voxproj'}
WEIGHTS = {'.onnx', '.pt', '.pth', '.ckpt', '.safetensors'}
FIXTURE = 'tests/fixtures/fleurs-mandarin.wav'
FIXTURE_SHA = 'a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b'
UPSTREAM = 'packaging/upstream/mingw-w64-lame-3.100-3.src.tar.zst'
UPSTREAM_SHA = 'dfd51143ea25aa0b67f5d355127b8a89a27379b1b128f0b2f9eed7c3327656ab'
CATALOG = 'tests/mc_corpus/sources.json'
# Pin reviewed content with LF line endings so Windows and POSIX checkouts agree.
# Accept the anonymized form too, supporting source-kit rebuilds without private names.
CATALOG_SHA = '7680c9d2a5c4a61bed68a98d741023e7978eca9a86d5bbe12c949e96f4892810'
PUBLIC_CATALOG_SHA = 'edf40fadda82bfce39b4d538a2ca1926de16f7631d7818054cde874b74a61bd6'
ROOT_FILES = frozenset({
    'app.py', 'requirements.txt', 'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'SECURITY.md', 'CODE_OF_CONDUCT.md', 'LICENSE', '.gitignore',
})
SOURCE_EXTENSIONS = {
    'vox': frozenset({'.py'}),
    'scripts': frozenset({'.py', '.ps1', '.sh'}),
    'tests': frozenset({'.py'}),
    # Markdown and screenshots are developer-facing documentation. Raw evidence
    # logs/data (txt, log, xml, json, jsonl) stay out of a source release.
    'docs': frozenset({'.md', '.png'}),
    '.github': frozenset({'.md', '.yml', '.yaml'}),
}
PACKAGING_EXTENSIONS = frozenset({'.py', '.ps1', '.sh', '.iss', '.spec'})
EXACT_FILES = frozenset({
    '.github/CODEOWNERS', 'tests/fixtures/README.md', 'tests/mc_corpus/README.md',
    'packaging/VoxMasterAI.ico', 'packaging/version.txt', UPSTREAM, CATALOG,
})


def _public_catalog(path):
    raw = path.read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(raw).hexdigest() not in {CATALOG_SHA, PUBLIC_CATALOG_SHA}:
        raise ValueError('Corpus catalog changed; review privacy and update the approved hashes')
    items = json.loads(raw)
    for item in items:
        if item['location'] == 'local':
            item['file'] = item['id'] + Path(item['file']).suffix
    return (json.dumps(items, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _allowed(relative):
    name = relative.as_posix()
    if name in ROOT_FILES or name in EXACT_FILES:
        return True
    parts = relative.parts
    if not parts:
        return False
    scope = parts[0]
    suffix = relative.suffix.casefold()
    if scope == 'packaging':
        if suffix in PACKAGING_EXTENSIONS:
            return True
        return len(parts) > 2 and parts[1].casefold() == 'licenses' and suffix == '.txt'
    return len(parts) > 1 and scope in SOURCE_EXTENSIONS and suffix in SOURCE_EXTENSIONS[scope]


def _is_inside(root, path):
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def _is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0)
        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    )


def _walk_error(error):
    raise error


def _scope_files(base):
    if not base.exists() or _is_link(base):
        return
    if not base.is_dir():
        yield base
        return
    for folder, directories, files in os.walk(base, followlinks=False, onerror=_walk_error):
        parent = Path(folder)
        # Python 3.11 does not classify Windows junctions as symbolic links.
        # Prune before descent so aliases cannot expose private files or loop.
        directories[:] = [
            name for name in directories
            if name.casefold() not in PRIVATE_CASEFOLDED and not _is_link(parent / name)
        ]
        yield from (parent / name for name in files)


def source_files(root):
    root = Path(root).resolve()
    license_path = root / 'LICENSE'
    if (not license_path.is_file() or _is_link(license_path)
            or not _is_inside(root, license_path)):
        raise ValueError('Root LICENSE is required in the source archive')
    for scope in SCOPES:
        base = root / scope
        paths = sorted(_scope_files(base))
        for path in paths:
            relative = path.relative_to(root)
            if not path.is_file():
                continue
            if any(part.casefold() in PRIVATE_CASEFOLDED for part in relative.parts):
                continue
            if _is_link(path) or not _is_inside(root, path):
                continue
            if any(_is_link(root / parent) for parent in relative.parents if parent != Path('.')):
                continue
            name = relative.as_posix()
            if name == FIXTURE:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != FIXTURE_SHA:
                    raise ValueError('Licensed FLEURS fixture was replaced; refusing to package audio')
            elif name == UPSTREAM:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != UPSTREAM_SHA:
                    raise ValueError('Approved upstream source archive changed; refusing to package it')
            elif name == CATALOG:
                _public_catalog(path)
            elif not _allowed(relative):
                continue
            yield path, name


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
                if name == CATALOG:
                    output.writestr(name, _public_catalog(path))
                else:
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
