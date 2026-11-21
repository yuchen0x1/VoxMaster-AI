"""Build a source archive without private media, cached models or local build state."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
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
REVIEWED_MERGED_CATALOG_SHA = '6697612412aee3a7a3e91f64d1fba2e732690624dd4b83f1898676812b3eadff'
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
_REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


def _public_catalog(path):
    return _catalog_bytes(path.read_bytes())


def _catalog_bytes(raw):
    raw = raw.replace(b'\r\n', b'\n')
    if hashlib.sha256(raw).hexdigest() not in {
        CATALOG_SHA, PUBLIC_CATALOG_SHA, REVIEWED_MERGED_CATALOG_SHA,
    }:
        raise ValueError('Corpus catalog changed; review privacy and update the approved hashes')
    items = json.loads(raw)
    for item in items:
        if item['location'] == 'local':
            item['file'] = item['id'] + Path(item['file']).suffix
    return json.dumps(items, ensure_ascii=False, indent=2).encode('utf-8')


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
    try:
        info = path.lstat()
    except OSError:
        # An unreadable or disappearing path is unsafe, not evidence of a regular file.
        return True
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & _REPARSE_POINT
    )


def _walk_error(error):
    raise error


def _scope_files(base):
    try:
        info = base.lstat()
    except FileNotFoundError:
        return
    if _is_link(base):
        return
    if not stat.S_ISDIR(info.st_mode):
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


def _tracked_paths(root):
    # Capture flags and immutable blob IDs in one index snapshot. Never fall back
    # to a filesystem walk, clear flags, or read a later version of the index.
    result = subprocess.run(
        ['git', '-C', str(root), 'ls-files', '--cached', '--stage', '-v', '-z', '--', *SCOPES],
        check=True, capture_output=True,
    )
    paths = {}
    for entry in result.stdout.decode('utf-8').split('\0'):
        if not entry:
            continue
        flag, separator, record = entry.partition(' ')
        if not separator or flag != 'H':
            raise ValueError(f'Unsupported Git index flag for source input: {entry}')
        metadata, separator, name = record.partition('\t')
        fields = metadata.split(' ')
        if (not separator or len(fields) != 3 or fields[0] not in {'100644', '100755'}
                or fields[2] != '0' or len(fields[1]) not in {40, 64}
                or any(char not in '0123456789abcdef' for char in fields[1])):
            raise ValueError(f'Unsupported Git index entry for source input: {entry}')
        paths[root / name] = fields[1]
    if root / 'LICENSE' not in paths:
        raise ValueError('Root LICENSE must be a tracked source input')
    clean = subprocess.run(
        ['git', '-C', str(root), 'diff', '--quiet', '--', *SCOPES],
        check=False, capture_output=True,
    )
    if clean.returncode:
        if clean.returncode == 1:
            raise ValueError('Working tree differs from the staged source archive inputs')
        raise subprocess.CalledProcessError(clean.returncode, clean.args)
    return paths


def _source_entries(root):
    supplied_root = Path(root).absolute()
    # Walk lexical ancestors first: resolving even a regular child would already
    # follow an ancestor symlink/junction and conceal the supplied alias.
    for path in reversed((supplied_root, *supplied_root.parents)):
        if _is_link(path):
            raise ValueError('Source root or ancestor must not be a symlink or reparse point')
        if not path.is_dir():
            raise ValueError('Source root must be a regular directory')
    root = supplied_root.resolve()
    if supplied_root != root:
        raise ValueError('Source root must be a regular directory')

    license_path = root / 'LICENSE'
    if _is_link(license_path) or not license_path.is_file() or not _is_inside(root, license_path):
        raise ValueError('Root LICENSE must be a regular file in the source archive')

    git_entry = root / '.git'
    try:
        git_entry.lstat()
    except FileNotFoundError:
        has_git = False
    except OSError as exc:
        raise ValueError('Cannot inspect source repository metadata') from exc
    else:
        has_git = True

    if has_git:
        paths = _tracked_paths(root)
    else:
        # A distributed source kit has no .git metadata and remains rebuildable.
        paths = {}
        for scope in SCOPES:
            paths.update((path, None) for path in _scope_files(root / scope))

    for path, object_id in sorted(paths.items()):
        relative = path.relative_to(root)
        if any(part.casefold() in PRIVATE_CASEFOLDED for part in relative.parts):
            continue
        name = relative.as_posix()

        linked = _is_link(path)
        for parent in path.parents:
            if parent == root:
                break
            linked = linked or _is_link(parent)
        inside = _is_inside(root, path)
        if has_git and (linked or not inside or not path.is_file()):
            raise ValueError(f'Unsafe tracked source input: {name}')
        if linked or not inside or not path.is_file():
            continue

        if name != FIXTURE and not _allowed(relative):
            continue
        yield path, name, object_id


def _reviewed_bytes(name, raw):
    # Validate the exact captured bytes, never a separate earlier read of a file
    # that ZipFile.write could reopen after validation.
    if name == FIXTURE and hashlib.sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError('Licensed FLEURS fixture was replaced; refusing to package audio')
    if name == UPSTREAM and hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA:
        raise ValueError('Approved upstream source archive changed; refusing to package it')
    if name == CATALOG:
        return _catalog_bytes(raw)
    return raw


def _read_source_bytes(path):
    for component in reversed((path, *path.parents)):
        if _is_link(component):
            raise ValueError(f'Unsafe source input changed before capture: {path}')
    if not path.is_file():
        raise ValueError(f'Source input is not a regular file: {path}')
    return path.read_bytes()


def source_files(root):
    for path, name, _ in _source_entries(root):
        if name in {FIXTURE, UPSTREAM, CATALOG}:
            _reviewed_bytes(name, _read_source_bytes(path))
        yield path, name


def _index_bytes(root, object_ids):
    # Read the captured blob IDs, not :path or smudged/clean-filtered live files.
    # This both accepts CRLF checkouts and prevents edits after git diff from
    # becoming archive payloads. Replacement refs must not redirect these reads.
    result = subprocess.run(
        ['git', '--no-replace-objects', '-C', str(root), 'cat-file', '--batch'],
        input=''.join(object_id + '\n' for object_id in object_ids).encode('ascii'),
        check=True, capture_output=True,
    )
    stream = io.BytesIO(result.stdout)
    for object_id in object_ids:
        fields = stream.readline().decode('ascii').rstrip('\n').split(' ')
        if len(fields) != 3 or fields[:2] != [object_id, 'blob'] or not fields[2].isdigit():
            raise ValueError(f'Cannot read reviewed Git blob: {object_id}')
        raw = stream.read(int(fields[2]))
        header = b'blob ' + str(len(raw)).encode('ascii') + b'\0'
        digest = hashlib.new('sha1' if len(object_id) == 40 else 'sha256', header + raw)
        if (len(raw) != int(fields[2]) or stream.read(1) != b'\n'
                or digest.hexdigest() != object_id):
            raise ValueError(f'Reviewed Git blob content mismatch: {object_id}')
        yield raw
    if stream.read(1):
        raise ValueError('Unexpected data after reviewed Git blobs')


def _assert_safe_archive_destination(destination):
    # Inspect the lexical absolute path with lstat before any mkdir/resolve; a
    # resolved path could conceal that the caller supplied an external link.
    for path in reversed((destination, *destination.parents)):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f'Cannot inspect archive destination path: {path}') from exc
        if stat.S_ISLNK(info.st_mode) or bool(
            getattr(info, 'st_file_attributes', 0) & _REPARSE_POINT
        ):
            raise ValueError(f'Archive destination path contains a symlink or reparse point: {path}')
        if path == destination and not stat.S_ISREG(info.st_mode):
            raise ValueError(f'Archive destination must be a regular file: {path}')
        if path != destination and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'Archive destination parent is not a directory: {path}')


def archive(destination, root=ROOT):
    destination = Path(destination).absolute()
    if destination.suffix.lower() != '.zip':
        raise ValueError('Source archive must use a .zip extension')
    _assert_safe_archive_destination(destination)
    root = Path(root).absolute()
    files = list(_source_entries(root))
    _assert_safe_archive_destination(destination)
    resolved_destination = destination.resolve(strict=False)
    if any(resolved_destination == path.resolve() for path, _, _ in files):
        raise ValueError('Archive must not replace any source file')

    if files and files[0][2] is not None:
        contents = _index_bytes(root, [object_id for _, _, object_id in files])
    else:
        contents = (_read_source_bytes(path) for path, _, _ in files)
    # Capture and validate everything before opening the ZIP. Writing must never
    # reopen live inputs after index/hash validation, including source-kit pins.
    payloads = [
        (name, _reviewed_bytes(name, raw))
        for (_, name, _), raw in zip(files, contents, strict=True)
    ]
    _assert_safe_archive_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_safe_archive_destination(destination)
    fd, temporary = tempfile.mkstemp(prefix='.vox-source-', suffix='.zip', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w+b') as stream:
            with ZipFile(stream, 'w', ZIP_DEFLATED, compresslevel=6) as output:
                for name, raw in payloads:
                    output.writestr(name, raw)
        _assert_safe_archive_destination(destination)
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
