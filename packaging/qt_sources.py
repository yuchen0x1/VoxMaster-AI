"""Prepare the matching Qt sources as a separate redistributable archive."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import zipfile
import tarfile

import requests

root = Path(__file__).resolve().parents[1]
destination = root / "build" / "qt-sources"
destination.mkdir(parents=True, exist_ok=True)
version = "6.12.0"
qt = f"https://download.qt.io/archive/qt/6.12/{version}/submodules/"
bindings = f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/"
urls = [qt + x + f"-everywhere-src-{version}.tar.xz" for x in ("qtbase", "qtsvg", "qtimageformats")]
urls.append(bindings + f"pyside-setup-everywhere-src-{version}.tar.xz")


def fetch(url):
    path = destination / url.rsplit("/", 1)[1]
    checksum = requests.get(url + ".sha256", timeout=25)
    checksum.raise_for_status()
    digest = checksum.text.strip().split()[0].lower()
    if not (path.is_file() and sha256(path.read_bytes()).hexdigest() == digest):
        with requests.get(url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            with path.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"SHA-256 mismatch for {path.name}")
    print(path.name, digest, flush=True)
    return path, digest


if __name__ == "__main__":
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(fetch, urls))
    output = root / "dist" / "Qt-6.12.0-Corresponding-Sources.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for path, digest in results:
            archive.write(path, path.name)
        archive.writestr("SHA256SUMS.txt", "".join(f"{digest}  {path.name}\n" for path, digest in results))


    # Preserve the original locations and exact upstream text of Qt attributions.
    with zipfile.ZipFile(destination / "Qt-notices.zip", "w", zipfile.ZIP_DEFLATED) as notices:
        for path, _ in results:
            with tarfile.open(path) as source:
                for member in source:
                    name = Path(member.name).name.lower()
                    included = "/LICENSES/" in member.name or (
                        "/3rdparty/" in member.name and
                        any(w in name for w in ("license", "copying", "copyright", "qt_attribution"))
                    )
                    if included and member.isfile() and member.size < 1024 * 1024:
                        notices.writestr(member.name, source.extractfile(member).read())
