"""Prepare a PyInstaller onedir for shipping with the audio-only FFmpeg build."""
import ctypes
import hashlib
import json
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys
import pefile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist/VoxMasterAI"
RUNTIME = DIST / "_internal"
CODECS = ROOT / "build/codecs"
INFO = DIST / "ThirdParty"
HASHED = re.compile(r"(-[0-9a-f]{32})(?=\.dll$)", re.I)


def install_codecs():
    import av
    stock = Path(av.__file__).resolve().parents[1] / "av.libs"
    original = {p.name.lower() for p in stock.glob("*.dll")}
    libraries = {p.name.lower() for p in CODECS.glob("*.dll")}
    if not {"avcodec-62.dll", "libmp3lame-0.dll", "libwinpthread-1.dll"} <= libraries:
        raise SystemExit("Build the pinned LGPL codec libraries first")
    # Delvewheel embeds unique names in the import table of the upstream
    # Python extensions. Restore the canonical ABI-major names of our DLLs.
    for file in (RUNTIME / "av").rglob("*.pyd"):
        data = bytearray(file.read_bytes())
        with pefile.PE(data=data, fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                old = entry.dll.decode("ascii").lower()
                if old not in original:
                    continue
                new = HASHED.sub("", old)
                if new not in libraries:
                    raise ValueError(f"Missing replacement for {old}")
                offset = pe.get_offset_from_rva(entry.struct.Name)
                data[offset:offset+len(old)] = new.encode().ljust(len(old), b"\x00")
        file.write_bytes(data)
    for file in RUNTIME.rglob("*.dll"):
        if file.name.lower() in original:
            file.unlink()
    folder = RUNTIME / "av.libs"
    folder.mkdir(exist_ok=True)
    for src in CODECS.glob("*.dll"):
        shutil.copy2(src, folder / src.name)
    import os
    with os.add_dll_directory(str(folder)):
        lib = ctypes.CDLL(str(folder / "avcodec-62.dll"))
        lib.avcodec_license.restype = lib.avcodec_configuration.restype = ctypes.c_char_p
        license_text = lib.avcodec_license().decode()
        conf = lib.avcodec_configuration().decode()
        if "LGPL" not in license_text or "--enable-gpl" in conf or "--enable-nonfree" in conf:
            raise ValueError("Unexpected FFmpeg build")
        (INFO / "FFmpeg-build.txt").write_text(license_text + "\n" + conf, "utf-8")


def copy_licenses():
    # Include both library notices and build-tool notices. Metadata identifies
    # the provenance of each wheel; bundled BLAS/LAPACK notices live in these files.
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        dest = INFO / "Python" / (name + "-" + dist.version)
        dest.mkdir(parents=True, exist_ok=True)
        for relative in dist.files or []:
            path = Path(relative)
            if path.parts[0] == "..":
                continue
            is_notice = any(word in path.name.upper() for word in ("LICENSE", "LICENCE", "COPYING", "THIRDPARTYNOTICES"))
            if is_notice or path.name == "METADATA" or "licenses" in path.parts:
                file = Path(dist.locate_file(relative))
                if file.is_file():
                    target = dest / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
    shutil.copy2(ROOT / "build/qt-sources/Qt-notices.zip", INFO)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", INFO / "Python-LICENSE.txt")
    shutil.copytree(ROOT / "packaging/licenses", INFO / "licenses", dirs_exist_ok=True)
    for name in ["ffmpeg-8.1.2.tar.xz", "COPYING.FFmpeg", "COPYING.winpthreads"]:
        shutil.copy2(CODECS / name, INFO / name)
    shutil.copy2(ROOT / "packaging/upstream/mingw-w64-lame-3.100-3.src.tar.zst", INFO)
    shutil.copy2(ROOT / "packaging/build-codecs.sh", INFO)


def copy_documents():
    # Include test evidence and hearing forms published alongside the manual.
    for doc in (ROOT / "docs").rglob("*"):
        if doc.is_file() and doc.suffix.lower() in {".md", ".png", ".json", ".jsonl", ".csv", ".txt"}:
            target = DIST / doc.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(doc, target)
    for name in ["README.md", "CHANGELOG.md"]:
        shutil.copy2(ROOT / name, DIST)
    shutil.copy2(ROOT / "docs/THIRD_PARTY.md", INFO)



def frozen_inputs():
    files = [
        ROOT / "app.py", ROOT / "requirements.txt", ROOT / "packaging/VoxMasterAI.spec",
        ROOT / "packaging/version.txt", ROOT / "packaging/VoxMasterAI.ico",
        DIST / "VoxMasterAI.exe", *sorted((ROOT / "vox").rglob("*.py")),
    ]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


if __name__ == "__main__":
    receipt = ROOT / "build/frozen-inputs.json"
    if sys.argv[1:] == ["--package"]:
        if json.loads(receipt.read_text("utf-8")) != frozen_inputs():
            raise SystemExit("Application sources or executable changed. Run build.ps1 -Phase Freeze first.")
        copy_documents()
    elif sys.argv[1:] == ["--freeze"]:
        INFO.mkdir(exist_ok=True)
        install_codecs()
        copy_licenses()
        receipt.write_text(json.dumps(frozen_inputs(), indent=2), encoding="utf-8")
    else:
        raise SystemExit("Use --freeze or --package")
