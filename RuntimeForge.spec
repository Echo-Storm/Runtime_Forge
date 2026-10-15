import os
# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Runtime Forge — onedir (folder) build.
#
# Build with:
#   venv\Scripts\pyinstaller.exe RuntimeForge.spec --clean
#
# Output lands in dist\RuntimeForge\ — copy that whole folder to
# distribute. uac_admin=True embeds a manifest that makes Windows prompt for
# elevation automatically on launch (replaces the PS1 original's separate
# RUN_ME.bat elevation wrapper). Settings/log files are written next to the
# exe (see core/paths.py) — the folder is fully self-contained and portable.

a = Analysis(
    ['runtime_forge.py'],
    pathex=[],
    binaries=[],
    # Bundles the whole assets/ folder (lands in _internal/assets with
    # PyInstaller 6+; resolved at runtime via core.paths.get_bundle_dir()) —
    # needed now that windows_terminal_settings.json is a real runtime-read
    # data file, not just a build-time icon resource like everything
    # previously in here.
    datas=[('assets', 'assets')],
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
    name='RuntimeForge',
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
    # Set RF_NO_ADMIN=1 to build a copy that doesn't demand elevation (for
    # testing the UI); release builds must leave it unset.
    uac_admin=os.environ.get('RF_NO_ADMIN') != '1',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RuntimeForge',
)
