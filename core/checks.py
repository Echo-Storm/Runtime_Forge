"""
Presence-check primitives: registry lookups, file/PE-version reads, command
probes. Each component in definitions.py composes these into its own
is_installed() check.
"""

import ctypes
import os
import re
import shutil
import subprocess
import threading
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

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


def reg_value_name_matches(hive: str, subkey: str, name_prefix: str) -> Optional[str]:
    """Returns the first value NAME under subkey that starts with
    name_prefix, or None. For registrations like .NET's
    InstalledVersions\\<arch>\\sharedfx\\<Name>, where each installed patch
    is recorded as a value name (e.g. "8.0.10") rather than a subkey —
    reg_key_exists() would never match here since there's no such subkey
    to open."""
    try:
        with winreg.OpenKey(_HIVES[hive], subkey) as key:
            i = 0
            while True:
                try:
                    value_name, _, _ = winreg.EnumValue(key, i)
                except OSError:
                    return None
                i += 1
                if value_name.startswith(name_prefix):
                    return value_name
    except OSError:
        return None


def file_exists(path: str) -> bool:
    return Path(path).is_file()


def dir_exists(path: str) -> bool:
    return Path(path).is_dir()


def _numeric_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name))


def any_child_dir_matches(base_dir: str, name_prefix: str) -> Optional[Path]:
    """Mirrors `Get-ChildItem <base> -Directory | Where Name -like "<prefix>*"`
    — used for the Adoptium JDK install folders, which embed the exact patch
    version in the directory name (e.g. jdk-21.0.4.7-hotspot)."""
    base = Path(base_dir)
    if not base.is_dir():
        return None
    matches = [c for c in base.iterdir() if c.is_dir() and c.name.startswith(name_prefix)]
    if not matches:
        return None
    # .NET runtimes/SDKs and JDKs install NEW versions beside the old ones
    # (10.0.11 and 10.0.13 both stay), so "the" install is the highest version -
    # not whichever folder the filesystem happens to list first. (Taking the
    # first made an already-updated component read as outdated forever.)
    return max(matches, key=lambda c: (_numeric_key(c.name), c.name))


def refresh_path_env() -> None:
    """Re-reads PATH from HKLM+HKCU into this process's environment.
    Needed after installers (e.g. winget) modify PATH — a running process
    otherwise never sees the change (the winget install step relies on this).

    Registry PATH entries can be REG_EXPAND_SZ containing literal %VAR%
    placeholders (confirmed on a real machine: dotnet's own installer
    writes "%USERPROFILE%\\.dotnet\\tools" verbatim) — winreg.QueryValueEx
    never expands these, so os.path.expandvars() has to run before the
    result is trusted as a real, walkable PATH. Skipping this would leave
    a literal "%USERPROFILE%\\..." entry in os.environ["Path"] that no
    lookup (shutil.which, subprocess's own search) will ever match against
    a real directory.
    """
    machine = reg_value(
        "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "Path"
    ) or ""
    user = reg_value("HKCU", "Environment", "Path") or ""
    combined = ";".join(p for p in (machine, user) if p)
    if combined:
        os.environ["Path"] = os.path.expandvars(combined)


def command_on_path(name: str) -> Optional[str]:
    """shutil.which, but re-checks after a PATH refresh so a just-installed
    tool is found without restarting the process."""
    found = shutil.which(name)
    if found:
        return found
    refresh_path_env()
    return shutil.which(name)


def is_dir_on_path(dir_path: Path) -> bool:
    """True if `dir_path` is one of the entries in the effective PATH
    (machine + user, refreshed from the registry first). This is a
    genuinely separate question from "does the installed binary run" —
    every install here already requests its own installer add itself to
    PATH (ADD_PATH=1, PrependPath=1, etc), but that request can silently
    fail, and a component whose is_installed() check runs the exe by its
    known absolute path (git/node/cmake/pwsh all do) would never notice."""
    refresh_path_env()
    target = str(dir_path.resolve()).rstrip("\\/").lower()
    raw = os.environ.get("Path", "")
    entries = (entry.strip().rstrip("\\/").lower() for entry in raw.split(";") if entry.strip())
    return target in entries


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


# (hive, key) pairs. Per-user installs (VS Code, Discord, Inno Setup 7, MSYS2
# via winget...) register under HKCU, not HKLM.
_UNINSTALL_ROOTS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


class UninstallCommand:
    def __init__(self, display_name: str, quiet_command: Optional[str], raw_command: Optional[str]):
        self.display_name = display_name
        self.quiet_command = quiet_command
        self.raw_command = raw_command


# A scan asks ~20 questions of the Uninstall and Installer\\Dependencies
# keys (one per VC++ redist, per uninstall action, ...). Each used to walk the
# whole registry subtree; now the subtree is read once into a snapshot that
# every lookup shares, until invalidate_registry_cache() (called at the start
# of each scan and after anything installs or uninstalls).
_snapshot_lock = threading.Lock()
_uninstall_snapshot: Optional[List[dict]] = None
_dependencies_snapshot: Optional[List[dict]] = None


def invalidate_registry_cache() -> None:
    global _uninstall_snapshot, _dependencies_snapshot
    with _snapshot_lock:
        _uninstall_snapshot = None
        _dependencies_snapshot = None


def _read_values(entry, names: tuple) -> dict:
    out = {}
    for name in names:
        try:
            out[name], _ = winreg.QueryValueEx(entry, name)
        except OSError:
            out[name] = None
    return out


def _read_subkeys(root_key, subkey_path: str, value_names: tuple) -> List[dict]:
    """Every immediate child of HKLM\\<subkey_path> that has a DisplayName,
    with the requested values (missing ones are None). Registry order kept."""
    rows: List[dict] = []
    try:
        with winreg.OpenKey(root_key, subkey_path) as parent:
            i = 0
            while True:
                try:
                    child_name = winreg.EnumKey(parent, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(parent, child_name) as entry:
                        values = _read_values(entry, value_names)
                except OSError:
                    continue
                if values.get("DisplayName"):
                    rows.append(values)
    except OSError:
        pass
    return rows


def _uninstall_entries() -> List[dict]:
    global _uninstall_snapshot
    with _snapshot_lock:
        if _uninstall_snapshot is None:
            rows: List[dict] = []
            for hive, root in _UNINSTALL_ROOTS:
                rows += _read_subkeys(
                    hive, root,
                    ("DisplayName", "DisplayVersion", "QuietUninstallString", "UninstallString"),
                )
            _uninstall_snapshot = rows
        return _uninstall_snapshot


def _dependency_entries() -> List[dict]:
    global _dependencies_snapshot
    with _snapshot_lock:
        if _dependencies_snapshot is None:
            _dependencies_snapshot = _read_subkeys(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\Installer\Dependencies",
                ("DisplayName", "Version"),
            )
        return _dependencies_snapshot


def find_uninstall_entry_by_display_name(pattern: "re.Pattern[str]") -> Optional[str]:
    """Scans the classic Programs-and-Features Uninstall keys (both the
    native and WOW6432Node views) for a DisplayName matching `pattern`,
    returning its DisplayVersion or None.

    Some older redistributables (2005, 2008) predate the MSI "provider key"
    dependency-tracking mechanism entirely (that's a 2012+ era feature) —
    they only ever show up here, in the same place Programs and Features
    itself reads from, not under Installer\\Dependencies.
    """
    for row in _uninstall_entries():
        if pattern.search(row["DisplayName"]):
            return row["DisplayVersion"] or row["DisplayName"]
    return None


def find_uninstall_command_by_display_name(pattern: "re.Pattern[str]") -> Optional[UninstallCommand]:
    """Same registry scan as find_uninstall_entry_by_display_name, but
    returns the actual uninstall command(s) instead of just the version —
    QuietUninstallString when the installer registered one (a vendor-
    provided silent invocation, fully trusted as-is), UninstallString
    otherwise (the caller may need to normalize it — confirmed on a real
    machine that several MSI packages register UninstallString with the
    literal text "/I{GUID}" — the install/repair verb, not "/X{GUID}" for
    remove — so it can't be executed as-is and trusted to actually
    uninstall anything).

    Always reads the registry fresh: an uninstall command must never come
    from a stale snapshot."""
    invalidate_registry_cache()
    for row in _uninstall_entries():
        if pattern.search(row["DisplayName"]):
            return UninstallCommand(row["DisplayName"], row["QuietUninstallString"], row["UninstallString"])
    return None


_shell32 = ctypes.WinDLL("shell32.dll")
_shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)


def parse_command_line(command: str) -> List[str]:
    """Parses a Windows command-line string (as found in registry
    UninstallString/QuietUninstallString values) into an argv list, using
    the same CommandLineToArgvW API Windows itself uses to parse a
    process's own command line — far more reliable for paths containing
    spaces and Windows-style backslash quoting than shlex, which assumes
    POSIX shell escaping rules."""
    argc = ctypes.c_int()
    argv_ptr = _shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv_ptr:
        return []
    try:
        return [argv_ptr[i] for i in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv_ptr)


_APPX_REPOSITORY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
    r"\AppModel\Repository\Packages"
)


def appx_package_version(name: str, publisher_id: str) -> Optional[str]:
    """Version of an installed MSIX/Appx package for the current user, read
    from the package repository in the registry - no PowerShell, no
    Get-AppxPackage. Package full names look like
    `Microsoft.WindowsTerminal_1.24.12741.0_x64__8wekyb3d8bbwe`
    (Name_Version_Arch_ResourceId_PublisherId); matching on both the name and
    the publisher id keeps e.g. Windows Terminal from matching its Preview
    sibling. Returns the highest installed version, or None."""
    prefix, suffix = f"{name}_", f"__{publisher_id}"
    best, best_key = None, ()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPX_REPOSITORY) as packages:
            i = 0
            while True:
                try:
                    full_name = winreg.EnumKey(packages, i)
                except OSError:
                    break
                i += 1
                if not (full_name.startswith(prefix) and full_name.endswith(suffix)):
                    continue
                version = full_name[len(prefix):].split("_", 1)[0]
                key = tuple(int(p) for p in re.findall(r"\d+", version))
                if key > best_key:
                    best, best_key = version, key
    except OSError:
        return None
    return best


_CBS_PACKAGES = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages"
_CBS_INSTALLED = 112  # 0x70: the package is installed (64 = staged but not installed)


def cbs_package_state(name_pattern: str) -> Optional[bool]:
    """Whether a Windows optional-feature package is installed, read from the
    Component Based Servicing registry (no dism, no elevation needed).
    True if any package whose name matches `name_pattern` is installed, False
    if some match but none are installed, None if nothing matches at all (the
    feature doesn't exist on this Windows build)."""
    pattern = re.compile(name_pattern)
    matched = False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CBS_PACKAGES) as packages:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(packages, i)
                except OSError:
                    break
                i += 1
                if not pattern.search(name):
                    continue
                matched = True
                try:
                    with winreg.OpenKey(packages, name) as package:
                        if winreg.QueryValueEx(package, "CurrentState")[0] == _CBS_INSTALLED:
                            return True
                except OSError:
                    continue
    except OSError:
        return None
    return False if matched else None


def find_dependency_by_display_name(pattern: "re.Pattern[str]") -> Optional[str]:
    """Scans HKLM\\SOFTWARE\\Classes\\Installer\\Dependencies\\* for a
    DisplayName matching `pattern`, returning its Version or None.

    Modern VC++ redistributable installers (14.30+) don't always populate
    the classic VisualStudio\\<ver>\\VC\\VCRedist registry key that older
    ones did — but they do register here, which is also what Programs and
    Features reads from. Falls back to this only when the classic key
    check comes up empty.
    """
    for row in _dependency_entries():
        if pattern.search(row["DisplayName"]):
            return row["Version"] or row["DisplayName"]
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
