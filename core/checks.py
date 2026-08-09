"""
Presence-check primitives, ported from the -IsInstalled scriptblocks in
ALLTHERUNTIMES.ps1 (registry Test-Path / Get-ItemProperty, file Test-Path,
Get-Command). Each component in definitions.py composes these into its own
is_installed() check, same as the PS1 composes Test-Path + Get-ItemProperty
inline per component.
"""

import os
import shutil
import subprocess
import winreg
from pathlib import Path
from typing import Optional

_HIVES = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER,
}


def reg_key_exists(hive: str, subkey: str) -> bool:
    try:
        with winreg.OpenKey(_HIVES[hive], subkey):
            return True
    except OSError:
        return False


def reg_value(hive: str, subkey: str, name: str) -> Optional[str]:
    """Returns the named value under subkey, or None if the key/value is missing."""
    try:
        with winreg.OpenKey(_HIVES[hive], subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def reg_value_int(hive: str, subkey: str, name: str) -> Optional[int]:
    v = reg_value(hive, subkey, name)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def file_exists(path: str) -> bool:
    return Path(path).is_file()


def dir_exists(path: str) -> bool:
    return Path(path).is_dir()


def any_child_dir_matches(base_dir: str, name_prefix: str) -> Optional[Path]:
    """Mirrors `Get-ChildItem <base> -Directory | Where Name -like "<prefix>*"`
    — used for the Adoptium JDK install folders, which embed the exact patch
    version in the directory name (e.g. jdk-21.0.4.7-hotspot)."""
    base = Path(base_dir)
    if not base.is_dir():
        return None
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith(name_prefix):
            return child
    return None


def refresh_path_env() -> None:
    """Re-reads PATH from HKLM+HKCU into this process's environment.
    Needed after installers (e.g. winget) modify PATH — a running process
    otherwise never sees the change, same problem the PS1 patches around
    after the winget install step."""
    machine = reg_value(
        "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "Path"
    ) or ""
    user = reg_value("HKCU", "Environment", "Path") or ""
    combined = ";".join(p for p in (machine, user) if p)
    if combined:
        os.environ["Path"] = combined


def command_on_path(name: str) -> Optional[str]:
    """shutil.which, but re-checks after a PATH refresh so a just-installed
    tool is found without restarting the process."""
    found = shutil.which(name)
    if found:
        return found
    refresh_path_env()
    return shutil.which(name)


def command_version(exe_path: str, args: list[str]) -> Optional[str]:
    """Runs `<exe> <args>` and returns stripped stdout, or None on any failure."""
    try:
        result = subprocess.run(
            [exe_path, *args],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = result.stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None
