# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).resolve().parent
source_root = project_root / "src"
migrations = source_root / "ytmp3studio" / "persistence" / "migrations"
ffmpeg = project_root / "tools" / "ffmpeg.exe"

datas = [
    (str(migrations), "ytmp3studio/persistence/migrations"),
    *collect_data_files("yt_dlp"),
]
binaries = [(str(ffmpeg), "tools")] if ffmpeg.is_file() else []
hiddenimports = collect_submodules("yt_dlp")

a = Analysis(
    [str(source_root / "ytmp3studio" / "__main__.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YT-MP3 Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(project_root / "packaging" / "version_info.txt"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="YT-MP3 Studio",
)
