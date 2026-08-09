"""
Presence-check primitives, ported from the -IsInstalled scriptblocks in
ALLTHERUNTIMES.ps1 (registry Test-Path / Get-ItemProperty, file Test-Path,
Get-Command). Each component in definitions.py composes these into its own
is_installed() check, same as the PS1 composes Test-Path + Get-ItemProperty
inline per component.
"""

import ctypes
import os
import re
import shutil
import subprocess
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Optional

_version_dll = ctypes.WinDLL("version.dll")
_version_dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version_dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version_dll.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
_version_dll.GetFileVersionInfoW.restype = wintypes.BOOL
_version_dll.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
_version_dll.VerQueryValueW.restype = wintypes.BOOL

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


def create_reg_marker_key(hive: str, subkey: str, values: dict[str, str]) -> bool:
    """Creates subkey (if missing) and sets the given string values on it.
    Used when a legacy installer's own silent registration can't be trusted
    to run — e.g. oalinst.exe's /S mode was confirmed (on a real machine) to
    exit 0 without writing anything at all, seemingly because it does its
    own internal version check against whatever OpenAL32.dll is already
    present and silently no-ops if that looks newer than what it would
    install. Writing the marker ourselves guarantees the actual thing games
    check for — the key's mere existence — regardless of that installer's
    own undocumented behavior on modern Windows.
    """
    try:
        with winreg.CreateKeyEx(_HIVES[hive], subkey, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        return True
    except OSError:
        return False


def any_reg_key_exists(hive: str, subkeys: list[str]) -> bool:
    """True if any of the given subkeys exists under hive — some products
    (WebView2's per-machine Clients key, notably) register under
    WOW6432Node even on a 64-bit OS instead of the plain 64-bit view, so a
    single-path check can false-negative on a real install."""
    return any(reg_key_exists(hive, subkey) for subkey in subkeys)


_UNINSTALL_ROOTS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]


def find_uninstall_entry_by_display_name(pattern: "re.Pattern[str]") -> Optional[str]:
    """Scans the classic Programs-and-Features Uninstall keys (both the
    native and WOW6432Node views) for a DisplayName matching `pattern`,
    returning its DisplayVersion or None.

    Some older redistributables (2005, 2008) predate the MSI "provider key"
    dependency-tracking mechanism entirely (that's a 2012+ era feature) —
    they only ever show up here, in the same place Programs and Features
    itself reads from, not under Installer\\Dependencies.
    """
    for root in _UNINSTALL_ROOTS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as uninstall_key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(uninstall_key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(uninstall_key, subkey_name) as entry:
                            display_name, _ = winreg.QueryValueEx(entry, "DisplayName")
                            if pattern.search(display_name):
                                try:
                                    version, _ = winreg.QueryValueEx(entry, "DisplayVersion")
                                except OSError:
                                    version = None
                                return version or display_name
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def find_dependency_by_display_name(pattern: "re.Pattern[str]") -> Optional[str]:
    """Scans HKLM\\SOFTWARE\\Classes\\Installer\\Dependencies\\* for a
    DisplayName matching `pattern`, returning its Version or None.

    Modern VC++ redistributable installers (14.30+) don't always populate
    the classic VisualStudio\\<ver>\\VC\\VCRedist registry key that older
    ones did — but they do register here, which is also what Programs and
    Features reads from. Falls back to this only when the classic key
    check comes up empty.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Installer\Dependencies") as deps_key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(deps_key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(deps_key, subkey_name) as entry:
                        display_name, _ = winreg.QueryValueEx(entry, "DisplayName")
                        if pattern.search(display_name):
                            try:
                                version, _ = winreg.QueryValueEx(entry, "Version")
                            except OSError:
                                version = None
                            return version or display_name
                except OSError:
                    continue
    except OSError:
        pass
    return None


def dll_version_field(path: str, field_name: str) -> Optional[str]:
    """Reads a named string from a PE file's VERSIONINFO resource (e.g.
    "ProductName", "ProductVersion"). Used to tell apart two DLLs that share
    a filename but not an identity — e.g. OpenAL Soft's soft_oal.dll
    (ProductName "OpenAL Soft") copied over OpenAL32.dll versus a generic
    reference implementation dropped there by something else entirely
    (confirmed on a real machine: an NVIDIA-bundled OpenAL32.dll reporting
    ProductName "Standard OpenAL(TM) Library" at that same path)."""
    size = _version_dll.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not _version_dll.GetFileVersionInfoW(path, 0, size, buf):
        return None

    trans_ptr = ctypes.c_void_p()
    trans_len = wintypes.UINT()
    if not _version_dll.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(trans_ptr), ctypes.byref(trans_len)):
        return None
    if trans_len.value < 4:
        return None
    words = ctypes.cast(trans_ptr, ctypes.POINTER(ctypes.c_ushort * (trans_len.value // 2))).contents
    lang, codepage = words[0], words[1]

    sub_block = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field_name}"
    value_ptr = ctypes.c_void_p()
    value_len = wintypes.UINT()
    if not _version_dll.VerQueryValueW(buf, sub_block, ctypes.byref(value_ptr), ctypes.byref(value_len)):
        return None
    if not value_len.value:
        return None
    return ctypes.wstring_at(value_ptr, value_len.value - 1)


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
