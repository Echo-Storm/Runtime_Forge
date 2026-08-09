# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for AIO Runtime Installer — onedir (folder) build.
#
# Build with:
#   venv\Scripts\pyinstaller.exe AIORuntimeInstaller.spec --clean
#
# Output lands in dist\AIORuntimeInstaller\ — copy that whole folder to
# distribute. uac_admin=True embeds a manifest that makes Windows prompt for
# elevation automatically on launch (replaces the PS1 original's separate
# RUN_ME.bat elevation wrapper). Settings/log files are written next to the
# exe (see core/paths.py) — the folder is fully self-contained and portable.

a = Analysis(
    ['aio_runtime_installer.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIORuntimeInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AIORuntimeInstaller',
)
