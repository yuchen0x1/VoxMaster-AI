"""Stage reviewed user documentation, not the developer's raw evidence tree."""
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from urllib.parse import quote, unquote, urlsplit

DOCUMENTS = ('MANUAL.md', 'MULTITRACK.md', 'MODELS.md', 'UPDATING.md',
             'PLATFORMS.md', 'THIRD_PARTY.md')
IMAGES = ('studio.png',)
SOURCE_URL = 'https://github.com/yuchen0x1/VoxMaster-AI/blob/main/'
LINK = re.compile(r'(!?\[[^\]\n]*\]\()([^\s)]+)(\))')
INDEX = '''# VoxMaster AI 离线帮助

- [使用手册：导入、调音、整曲处理、保存与导出](MANUAL.md)
- [多轨编排、监听与快捷键](MULTITRACK.md)
- [模型下载、校验、迁移与授权边界](MODELS.md)
- [官方更新与数据保护](UPDATING.md)
- [平台支持与未验边界](PLATFORMS.md)
- [第三方软件及再分发说明](THIRD_PARTY.md)

以上手册和图片随程序提供，可离线阅读。指向 GitHub 的研发报告、
历史验收与源码链接需要联网，且可能反映较新的源码状态。
原始测试日志、私人素材清单和开发机诊断不随安装包提供。
许可证正文及对应源码获取信息保留在程序的 ThirdParty 目录。
'''
README = '''# VoxMaster AI

本地优先的人声制作与歌曲混音工作站。启动 VoxMasterAI.exe，导入录音，
选择工作模式与风格，处理后可 A/B 试听并导出到新的文件名。
工程通过路径引用素材，请把 .voxproj 和素材一起备份。

[离线帮助与快捷键](docs/INDEX.md) · [MIT 许可证](LICENSE) ·
[版本与下载](https://github.com/yuchen0x1/VoxMaster-AI/releases) ·
[更新记录](https://github.com/yuchen0x1/VoxMaster-AI/blob/main/CHANGELOG.md)

不上传录音；模型按需获取，不随程序附带。分离质量需人工试听。
Windows 10 实机、系统代码签名及实体跨平台监听等限制见离线平台说明。
'''


def _linked(path):
    if path.is_symlink():
        return True
    if os.name == 'nt' and path.is_dir():
        # Path.is_junction is unavailable on the supported Python 3.11.
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _regular_file(root, relative):
    path = root / relative
    if (not path.is_file() or not path.resolve().is_relative_to(root)
            or any(_linked(p) for p in (path, *path.parents) if p != root)):
        raise ValueError(f'Required shipping document is missing or linked: {relative}')
    return path


def _links(text, relative, output_relative=None):
    shipped = {PurePosixPath('LICENSE'), *(PurePosixPath('docs') / n
               for n in (*DOCUMENTS, *IMAGES, 'INDEX.md'))}

    def replace(match):
        target = match[2]
        parsed = urlsplit(target)
        if parsed.scheme in {'https', 'http', 'mailto'}:
            return match[0]
        if parsed.scheme or parsed.netloc or '\\' in unquote(target):
            raise ValueError(f'Unsafe documentation link in {relative}')
        if not parsed.path:
            return match[0]
        parts = list(PurePosixPath(relative).parent.parts)
        path = PurePosixPath(unquote(parsed.path))
        if path.is_absolute():
            raise ValueError(f'Absolute documentation link in {relative}')
        for part in path.parts:
            if part == '..':
                if not parts:
                    raise ValueError(f'Escaping documentation link in {relative}')
                parts.pop()
            elif part != '.':
                parts.append(part)
        resolved = PurePosixPath(*parts)
        if resolved in shipped:
            if output_relative is None:
                return match[0]
            local = os.path.relpath(str(resolved), str(PurePosixPath(output_relative).parent)).replace('\\', '/')
            suffix = ('?' + parsed.query if parsed.query else '')
            suffix += '#' + parsed.fragment if parsed.fragment else ''
            return match[1] + quote(local) + suffix + match[3]
        if match[1].startswith('!'):
            raise ValueError(f'Unreviewed documentation image in {relative}')
        suffix = ('?' + parsed.query if parsed.query else '')
        suffix += '#' + parsed.fragment if parsed.fragment else ''
        return match[1] + SOURCE_URL + quote(resolved.as_posix()) + suffix + match[3]

    return LINK.sub(replace, text)


def copy_documents(root, destination):
    """Replace only build-owned docs; prepare and validate before touching staging."""
    root, destination = Path(root).resolve(), Path(destination).absolute()
    if any(_linked(p) for p in (destination, *destination.parents)):
        raise ValueError('Shipping document destination must not be linked')
    prefix = '.' + destination.name + '-docs-'
    if list(destination.glob('.vox-docs-*')) or list(destination.parent.glob(prefix + '*')):
        raise ValueError('Unresolved shipping document backup; recover it before packaging')
    if destination.resolve() == root or root.is_relative_to(destination.resolve()):
        raise ValueError('Shipping destination must not replace the source tree')
    payloads = {}
    for name in DOCUMENTS:
        relative = 'docs/' + name
        payloads[name] = _links(_regular_file(root, relative).read_text('utf-8'), relative).encode('utf-8')
    for name in IMAGES:
        payloads[name] = _regular_file(root, 'docs/' + name).read_bytes()
    license_data = _regular_file(root, 'LICENSE').read_bytes()
    payloads['INDEX.md'] = INDEX.encode('utf-8')
    destination.mkdir(parents=True, exist_ok=True)
    docs = destination / 'docs'
    info = destination / 'ThirdParty'
    targets = (docs, destination / 'README.md', destination / 'CHANGELOG.md',
               destination / 'LICENSE', info, info / 'THIRD_PARTY.md',
               info / 'VoxMaster-AI-LICENSE.txt')
    for path in targets:
        if _linked(path):
            raise ValueError('Shipping document destination must not be linked')
    notice = _links(_regular_file(root, 'docs/THIRD_PARTY.md').read_text('utf-8'),
                    'docs/THIRD_PARTY.md', 'ThirdParty/THIRD_PARTY.md').encode('utf-8')
    if docs.exists() and not docs.is_dir():
        raise ValueError('Shipping docs destination must be a directory')
    for path in targets:
        if path not in (docs, info) and path.exists() and not path.is_file():
            raise ValueError('Shipping notice destination must be a regular file')
    if info.exists() and not info.is_dir():
        raise ValueError('ThirdParty destination must be a directory')
    files = {'docs/' + name: data for name, data in payloads.items()}
    files.update({'README.md': README.encode('utf-8'), 'LICENSE': license_data,
                  'CHANGELOG.md': ('# 更新记录\n\n[完整更新记录（需联网）]('
                                   + SOURCE_URL + 'CHANGELOG.md)\n').encode('utf-8'),
                  'ThirdParty/THIRD_PARTY.md': notice,
                  'ThirdParty/VoxMaster-AI-LICENSE.txt': license_data})
    # Keep any emergency backup outside the recursively packaged application.
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=destination.parent))
    backup, prepared = folder / 'previous', folder / 'prepared'
    operations = []
    rollback_ok = True
    had_info = info.exists()
    try:
        for relative, data in files.items():
            path = prepared / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        info.mkdir(exist_ok=True)
        for relative in ('docs', 'README.md', 'LICENSE', 'CHANGELOG.md',
                         'ThirdParty/THIRD_PARTY.md', 'ThirdParty/VoxMaster-AI-LICENSE.txt'):
            target, old = destination / relative, backup / relative
            existed = target.exists()
            if existed:
                old.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, old)
            operations.append((relative, existed))
            os.replace(prepared / relative, target)
    except OSError:
        for relative, existed in reversed(operations):
            target, old = destination / relative, backup / relative
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                if existed:
                    os.replace(old, target)
            except OSError:
                rollback_ok = False
        if not had_info:
            try:
                info.rmdir()
            except OSError:
                pass
        if not rollback_ok:
            raise OSError(f'Document rollback failed; recover backup at {folder}')
        raise
    finally:
        if rollback_ok:
            shutil.rmtree(folder)
