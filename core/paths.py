"""
App base directory resolution — works the same whether running from source
or as a frozen PyInstaller build.
"""

import os
import shutil
import sys
from pathlib import Path


def get_app_dir() -> Path:
    """
    Folder everything portable (temp_installers/, settings, log files) lives
    next to.

    Frozen (PyInstaller): __file__ resolves inside the bundle (e.g. an
    onedir build's _internal/ folder), not next to the actual .exe, so we
    anchor on sys.executable instead — that's always the real exe's location
    regardless of onefile/onedir.

    Running from source: this file lives at <project_root>/core/paths.py.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_bundle_dir() -> Path:
    """
    Folder bundled read-only data files (assets/) live in.

    PyInstaller 6+ onedir builds put `datas` under _internal/ (sys._MEIPASS),
    not next to the exe like 5.x did, so assets can't be found via
    get_app_dir() once frozen. From source it's the project root, same as
    get_app_dir().
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


PORTABLE_MARKER = "portable.txt"
_LEGACY_ITEMS = ("profiles", "path_backups", "RuntimeForge.ini")


def get_data_dir() -> Path:
    """
    Where the user's own data lives: logs, RuntimeForge.ini, profiles/ and
    path_backups/.

    An installed (frozen) copy sits in Program Files, which is the wrong place
    for data the user wants to keep - it's lost or orphaned on uninstall and
    upgrade - so that goes to %LOCALAPPDATA%\\RuntimeForge instead. From
    source, or from a frozen copy with a `portable.txt` file next to the exe,
    everything stays next to the app as before.

    Installer staging (temp_installers/) deliberately does NOT move here: it
    must stay somewhere only an administrator can write, because the files in
    it are executed elevated. %LOCALAPPDATA% is writable by any unelevated
    process running as the same user.
    """
    override = os.environ.get("RUNTIME_FORGE_DATA_DIR")
    if override:
        # For tests and debugging: keep logs/profiles/backups out of the real locations.
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path

    app_dir = get_app_dir()
    if not getattr(sys, "frozen", False) or (app_dir / PORTABLE_MARKER).is_file():
        return app_dir

    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    data_dir = Path(base) / "RuntimeForge"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return app_dir  # can't create it - degrade to the old behaviour
    _migrate_legacy_data(app_dir, data_dir)
    return data_dir


def _migrate_legacy_data(old_dir: Path, new_dir: Path) -> None:
    """One-time move of data an older release wrote next to the exe. Never
    overwrites anything already in the new location, and ignores failures."""
    for name in _LEGACY_ITEMS:
        src, dst = old_dir / name, new_dir / name
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
            except OSError:
                pass
