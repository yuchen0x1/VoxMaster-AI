"""Authenticated release metadata and bounded, atomic downloads. No custom trust URLs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urljoin, urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import Version
import requests

from . import __version__
from .platforms import data_directory
from .update_key import PUBLIC_KEY

REPOSITORY = 'yuchen0x1/VoxMaster-AI'
RELEASES = 'https://github.com/' + REPOSITORY + '/releases'
MANIFEST = RELEASES + '/latest/download/update.json'
MAX_PACKAGE = 512 * 1024**2


def trusted_url(url):
    try:
        p = urlparse(url)
        return (p.scheme == 'https' and not (p.username or p.password) and p.port in (None, 443)
                and ((p.hostname == 'github.com' and p.path.startswith('/' + REPOSITORY + '/releases/'))
                     or p.hostname == 'release-assets.githubusercontent.com'))
    except ValueError:
        return False


def response(url, cancel=None):
    for _ in range(6):
        check_cancel(cancel)
        if not trusted_url(url):
            raise ValueError('更新下载来源不受信任。')
        r = requests.get(url, stream=True, allow_redirects=False, timeout=(8, 30),
                         headers={'Accept-Encoding': 'identity', 'User-Agent': 'VoxMasterAI/' + __version__})
        try:
            check_cancel(cancel)
            if r.status_code in (301, 302, 303, 307, 308):
                location = r.headers.get('Location', '')
                if not location:
                    raise ValueError('更新重定向缺少目标。')
                url = urljoin(url, location)
                r.close()
                continue
            r.raise_for_status()
        except Exception:
            r.close()
            raise
        return r
    raise ValueError('更新重定向次数过多。')


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('更新已取消。')


def fetch(url, limit, cancel=None):
    check_cancel(cancel)
    data = bytearray()
    with response(url, cancel) as r:
        for chunk in r.iter_content(65536):
            check_cancel(cancel)
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('更新响应超过大小限制。')
    check_cancel(cancel)
    return bytes(data)


def verify_manifest(body, signature):
    try:
        sig = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY)).verify(sig, body)
    except (ValueError, InvalidSignature) as exc:
        raise ValueError('更新数字签名校验失败。') from exc
    data = json.loads(body)
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('不支持此更新清单版本。')
    ver = Version(data['version'])
    if ver.is_prerelease or ver.is_devrelease or ver.local or ver.epoch:
        raise ValueError('正式更新通道不接受预览版本。')
    if Version(__version__) < Version(data['minimum_version']):
        raise ValueError('此版本需手动升级，请访问官方 Releases。')
    if not isinstance(data.get('notes'), str) or not isinstance(data.get('published_at'), str):
        raise ValueError('更新说明或发布日期无效。')
    assets = data.get('assets')
    if not isinstance(assets, dict):
        raise ValueError('缺少平台资产。')
    for key, asset in assets.items():
        name = asset['name']
        expected = RELEASES + '/download/v' + data['version'] + '/' + name
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or asset['url'] != expected
                or not re.fullmatch('[a-f0-9]{64}', asset['sha256'])
                or type(asset['size']) is not int or not 0 < asset['size'] <= MAX_PACKAGE):
            raise ValueError('更新资产元数据无效：' + key)
    return data


def check_release(cancel=None):
    body = fetch(MANIFEST, 65536, cancel)
    signature = fetch(MANIFEST + '.sig', 256, cancel).strip()
    check_cancel(cancel)
    return verify_manifest(body, signature)


def download(asset, cancel, progress, directory=None):
    check_cancel(cancel)
    root = Path(directory) if directory else data_directory() / 'updates'
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < asset['size'] + 32 * 1024**2:
        raise OSError('更新缓存磁盘空间不足。')
    # The digest, not a remote filename, determines the local destination.
    dest = root / (asset['sha256'] + Path(asset['name']).suffix)
    fd, tempname = tempfile.mkstemp(prefix='download-', suffix='.part', dir=root)
    temp = Path(tempname)
    count = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as out, response(asset['url'], cancel) as r:
            for chunk in r.iter_content(256 * 1024):
                if cancel.is_set():
                    raise InterruptedError('更新已取消。')
                count += len(chunk)
                if count > asset['size']:
                    raise ValueError('更新包超出签名清单长度。')
                digest.update(chunk)
                out.write(chunk)
                progress(count / asset['size'], f'{count // 1024} / {asset["size"] // 1024} KiB')
            out.flush()
            os.fsync(out.fileno())
        check_cancel(cancel)
        if count != asset['size'] or digest.hexdigest() != asset['sha256']:
            raise ValueError('更新包长度或 SHA-256 校验失败。')
        os.replace(temp, dest)
        return dest
    finally:
        temp.unlink(missing_ok=True)


def installer_asset(data):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('此平台请按安装指南使用源码更新，保留原有用户数据。')
    return data['assets']['windows-x64-setup']


def launch_installer(path, data):
    """Launch only a verified installer, after the user explicitly confirms installation."""
    asset = installer_asset(data)
    path = Path(path).resolve()
    if path.stat().st_size != asset['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
        raise ValueError('安装前复核失败，请重新下载。')
    if Version(data['version']) <= Version(__version__):
        raise ValueError('拒绝安装相同或更旧的更新。')
    # Interactive Inno Setup owns application-close prompts and per-user elevation policy.
    # No silent install and no claim of automatic rollback.
    return subprocess.Popen([str(path)], close_fds=True)
