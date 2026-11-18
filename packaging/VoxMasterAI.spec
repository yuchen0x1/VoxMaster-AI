from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
excluded = ["pytest", "_pytest", "tkinter", "unittest.test", "matplotlib", "IPython", "torch",
            "sympy", "mpmath", "onnx", "scipy.datasets", "PySide6.QtQml", "PySide6.QtQuick"]
# Device settings display these exact distribution versions in the frozen app.
runtime_metadata = []
for name in ("av", "scipy", "sounddevice", "pyside6-essentials", "onnxruntime-directml"):
    runtime_metadata.extend(copy_metadata(name))
analysis = Analysis([str(root / "app.py"), str(root / "scripts/cli_entry.py")], pathex=[str(root)], binaries=[], datas=runtime_metadata,
                    hiddenimports=["vox.package_check"], excludes=excluded, noarchive=False)

def allowed(item):
    name = item[0].replace("\\", "/").lower()
    if name.endswith("/opengl32sw.dll"):
        return False  # Qt Widgets uses the raster paint engine.
    if "libportaudio" in name:
        return name.endswith("/libportaudio64bit.dll")
    if name.startswith("pyside6/translations/"):
        return "zh_cn" in name or "qtbase_en" in name
    return True

analysis.binaries = [item for item in analysis.binaries if allowed(item)]
analysis.datas = [item for item in analysis.datas if allowed(item)]
pyz = PYZ(analysis.pure)
runtime_scripts = [item for item in analysis.scripts if Path(item[1]).name.startswith("pyi_rth_")]
gui_scripts = runtime_scripts + [item for item in analysis.scripts if Path(item[1]).name.lower() == "app.py"]
cli_scripts = runtime_scripts + [item for item in analysis.scripts if Path(item[1]).name.lower() == "cli_entry.py"]
exe = EXE(pyz, gui_scripts, [], exclude_binaries=True, name="VoxMasterAI",
          debug=False, strip=False, upx=False, console=False, version=str(root/"packaging"/"version.txt"),
          icon=str(root/"packaging"/"VoxMasterAI.ico"))
cli = EXE(pyz, cli_scripts, [], exclude_binaries=True, name="VoxMasterAI-CLI",
          debug=False, strip=False, upx=False, console=True, version=str(root/"packaging"/"version.txt"),
          icon=str(root/"packaging"/"VoxMasterAI.ico"))
dist = COLLECT(exe, cli, analysis.binaries, analysis.datas, strip=False, upx=False, name="VoxMasterAI")
