"""
Snapshot and restore the machine + user PATH environment variable.

This is separate from each component's own "set PATH correctly at install
time" flags (ADD_PATH=1 etc) — it's a safety net for the rarer but real
scenario where a batch of installs, a manual edit, or something else
garbles PATH afterward. Windows PATH corruption is notoriously hard to
recover from without knowing exactly what it looked like before, and by
the time someone notices, the "before" state is already gone — so this
snapshots automatically rather than needing to be remembered.

One backup per install run (a full "Install Selected" batch), not one per
component in it — a run installing 5 things makes 1 backup, not 5.
"""

import ctypes
import json
import winreg
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.logger import get_logger

_MACHINE_ENV_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_USER_ENV_KEY = r"Environment"
MAX_BACKUPS = 50


@dataclass
class PathBackup:
    timestamp: str  # ISO string
    reason: str      # e.g. "before installing 3 component(s)"
    machine_path: str
    user_path: str


def backups_dir(app_dir: Path) -> Path:
    d = app_dir / "path_backups"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # callers already handle a missing/unwritable dir gracefully
    return d


def _read_raw_path(hive: int, subkey: str) -> str:
    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
    except OSError:
        return ""


def read_current_path() -> tuple[str, str]:
    """Returns (machine_path, user_path) as they currently are in the
    registry — for comparing against a saved backup, e.g. in a restore
    confirmation dialog, without needing raw winreg access outside this
    module."""
    return (
        _read_raw_path(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY),
        _read_raw_path(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY),
    )


def create_backup(app_dir: Path, reason: str) -> Optional[Path]:
    machine_path, user_path = read_current_path()
    if not machine_path:
        # Machine PATH is never legitimately empty on a real Windows install
        # (System32 etc are always present) — an empty read here means the
        # registry read itself failed, not that PATH truly has no entries.
        # Saving it anyway would create a backup that, if ever restored,
        # wipes machine-wide PATH. (User PATH being empty IS legitimate for
        # plenty of accounts, so it alone doesn't block a backup.)
        get_logger().status("Could not read machine PATH (empty result) - skipping PATH backup")
        return None

    ts = datetime.now()
    backup = PathBackup(
        timestamp=ts.isoformat(timespec="seconds"),
        reason=reason,
        machine_path=machine_path,
        user_path=user_path,
    )
    # Two backups created within the same wall-clock second (e.g. a double
    # click, or a restore's own pre-restore safety backup landing in the
    # same second as one just made manually) would otherwise share this
    # exact filename and the second write would silently overwrite the
    # first - permanently destroying an earlier real backup's content,
    # which directly defeats "restoring itself takes a fresh backup first,
    # so it's never a one-way door." Confirmed reproducible: three
    # back-to-back create_backup() calls collapsed into one file before
    # this guard existed.
    base_dir = backups_dir(app_dir)
    path = base_dir / f"path_backup_{ts:%Y%m%d_%H%M%S}.json"
    suffix = 1
    while path.exists():
        path = base_dir / f"path_backup_{ts:%Y%m%d_%H%M%S}_{suffix}.json"
        suffix += 1
    try:
        path.write_text(json.dumps(asdict(backup), indent=2), encoding="utf-8")
    except OSError:
        return None

    _prune_old_backups(app_dir)
    return path


def _prune_old_backups(app_dir: Path) -> None:
    # 50 caps unbounded growth without ever meaningfully constraining a
    # realistic user — at a few backups a year, that's decades of history.
    backups = sorted(backups_dir(app_dir).glob("path_backup_*.json"), key=lambda p: p.name, reverse=True)
    for stale in backups[MAX_BACKUPS:]:
        stale.unlink(missing_ok=True)


def list_backups(app_dir: Path) -> List[PathBackup]:
    found = []
    for path in sorted(backups_dir(app_dir).glob("path_backup_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            machine_path = str(data.get("machine_path", ""))
            if not machine_path:
                # A backup file with no machine_path (corrupted, hand-
                # edited, or written before this guard existed) is not
                # something that should ever be selectable to restore —
                # fail closed at the read layer, not just at write time.
                get_logger().status(f"Skipping unusable PATH backup (empty machine path): {path.name}")
                continue
            found.append(PathBackup(
                timestamp=str(data["timestamp"]),
                reason=str(data.get("reason", "")),
                machine_path=machine_path,
                user_path=str(data.get("user_path", "")),
            ))
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
    return found


def restore_backup(backup: PathBackup) -> bool:
    """Writes machine_path/user_path back to the registry as REG_EXPAND_SZ
    — matching how Windows itself stores PATH, so %SystemRoot%-style
    placeholders keep resolving correctly instead of being frozen as
    literal text — then broadcasts WM_SETTINGCHANGE so already-running
    processes (Explorer, open terminal windows) pick up the change without
    a reboot. Some apps still only re-read env vars at their own startup
    regardless of the broadcast; that's a Windows limitation, not
    something a broadcast can force past.
    """
    if not backup.machine_path:
        # Refuse outright rather than trust the caller — writing an empty
        # machine PATH would break cmd/powershell path resolution
        # system-wide. (An empty user_path is allowed through below; that's
        # legitimate for plenty of accounts, not a sign of corruption.)
        get_logger().fail("Refusing to restore: backup has an empty machine PATH (would wipe it system-wide)")
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, backup.machine_path)
    except OSError:
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, backup.user_path)
    except OSError:
        pass  # machine PATH restore already succeeded; user PATH is best-effort

    _broadcast_environment_change()
    return True


def ensure_first_run_backup(app_dir: Path) -> None:
    """Snapshots PATH once, the very first time this app ever launches -
    before it has installed or changed anything. Mirrors
    profiles.ensure_default_profile()'s "only if nothing exists yet" shape:
    if any backup already exists (from a prior launch, a real install run,
    or a manual Backup Now click), this does nothing. The point is a known-
    good baseline from before this app touched the machine at all, since by
    the time someone notices a problem it's too late to capture that."""
    if list_backups(app_dir):
        return
    create_backup(app_dir, "first launch of Runtime Forge")


def add_directory_to_path(dir_path: Path) -> bool:
    """Appends dir_path to the machine PATH if it isn't already there.

    For the handful of components that ship as a raw binary with no
    installer of their own (ninja, jq) — everything else in this app gets
    its PATH entry from the vendor's own installer; these two have no such
    installer, so this app has to be the one to add it. Idempotent: if the
    exact directory is already present (case-insensitively, trailing slash
    ignored), does nothing and returns True rather than accumulating
    duplicate entries on repeated installs. Only ever appends — never
    removes or reorders anything already there.
    """
    machine_path, _ = read_current_path()
    if not machine_path:
        return False  # same "never trust an empty read" stance as create_backup()

    target = str(dir_path).rstrip("\\/").lower()
    entries = [e for e in machine_path.split(";") if e.strip()]
    if any(e.strip().rstrip("\\/").lower() == target for e in entries):
        return True  # already present

    new_path = machine_path.rstrip(";") + ";" + str(dir_path)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
    except OSError:
        return False

    _broadcast_environment_change()
    return True


def remove_directory_from_path(dir_path: Path) -> bool:
    """The uninstall counterpart to add_directory_to_path() — removes
    dir_path from the machine PATH if present (case-insensitively, trailing
    slash ignored), leaving every other entry's order untouched. Idempotent:
    if the directory isn't there, this is a no-op success, not a failure."""
    machine_path, _ = read_current_path()
    if not machine_path:
        return False  # same "never trust an empty read" stance as add_directory_to_path()

    target = str(dir_path).rstrip("\\/").lower()
    entries = [e for e in machine_path.split(";") if e.strip()]
    kept = [e for e in entries if e.strip().rstrip("\\/").lower() != target]
    if len(kept) == len(entries):
        return True  # wasn't there to begin with

    new_path = ";".join(kept)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
    except OSError:
        return False

    _broadcast_environment_change()
    return True


def _broadcast_environment_change() -> None:
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x1A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_long()
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
        SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
    )
