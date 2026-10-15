"""
App base directory resolution — works the same whether running from source
or as a frozen PyInstaller build.
"""

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
