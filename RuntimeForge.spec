# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Runtime Forge — onedir (folder) build.
#
# Build with:
#   venv\Scripts\python.exe -m PyInstaller RuntimeForge.spec --clean
# (use `python -m PyInstaller`, not venv\Scripts\pyinstaller.exe - that
# launcher silently does nothing when the venv has been moved.)
#
# Output lands in dist\RuntimeForge\ - copy that whole folder to
# distribute, or wrap it with installer\RuntimeForge.iss. uac_admin embeds a
# manifest that makes Windows prompt for elevation on every launch (replaces
# the PS1 original's separate RUN_ME.bat elevation wrapper); set RF_NO_ADMIN=1
# to build a copy that doesn't, for testing the UI. Release builds leave it
# unset. Where the app keeps its settings/logs/profiles/PATH backups is
# decided in core/paths.py (next to the exe when portable, otherwise
# %LOCALAPPDATA%\RuntimeForge).
import os

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
