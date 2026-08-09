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
