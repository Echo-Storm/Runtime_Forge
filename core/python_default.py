"""
Which Python does `python` mean?

Windows resolves `python` / `pip` by PATH order (machine PATH first, then user
PATH), so having several python.org Pythons installed means whichever one's
folder happens to come first wins - usually the one installed *last* or by the
oldest PATH entry, not the newest. This module:

  * discovers the python.org installs the way the `py` launcher does (PEP 514
    registry keys), so a Python in a custom folder (E:\\Python314) is found too;
  * plans a PATH change that leaves only the newest one as the default: its
    folder and Scripts folder go first on the machine PATH (machine entries
    outrank user entries), and the folders of every other
    python.org install (including their `%APPDATA%\\Python\\PythonXY` user-site
    folders) are removed. The other Pythons stay installed and keep working
    through the launcher (`py -3.12`).

planning is a pure function (`plan_make_default`) so it can be previewed and
tested; `apply_plan` is the only part that writes to the registry.
"""

import os
import re
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core import path_backup

_CORE_KEY = r"SOFTWARE\Python\PythonCore"
_VERSION_KEY = re.compile(r"^(\d+)\.(\d+)(?:-32|-arm64)?$")


@dataclass(frozen=True)
class PythonInstall:
    version: str                  # "3.14"
    key: Tuple[int, int]          # (3, 14)
    install_dir: Path
    exe: Path
    all_users: bool               # registered under HKLM (else HKCU)


@dataclass
class PathPlan:
    latest: PythonInstall
    new_machine: str
    new_user: str
    removed: List[Tuple[str, str]] = field(default_factory=list)   # (scope, entry)
    added: List[Tuple[str, str]] = field(default_factory=list)
    changed: bool = False


def _read_install(hive, view_flag: int, version_name: str) -> Optional[Tuple[Path, Path]]:
    try:
        with winreg.OpenKey(hive, rf"{_CORE_KEY}\{version_name}\InstallPath", 0, winreg.KEY_READ | view_flag) as key:
            install_dir = winreg.QueryValueEx(key, "")[0]
            try:
                exe = winreg.QueryValueEx(key, "ExecutablePath")[0]
            except OSError:
                exe = str(Path(install_dir) / "python.exe")
    except OSError:
        return None
    return Path(os.path.expandvars(install_dir)), Path(os.path.expandvars(exe))


def installed_pythons() -> List[PythonInstall]:
    """python.org installs registered under PythonCore (what `py -0p` lists,
    minus other distributions like Astral's or Store builds)."""
    found: dict = {}
    for hive, all_users in ((winreg.HKEY_LOCAL_MACHINE, True), (winreg.HKEY_CURRENT_USER, False)):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, _CORE_KEY, 0, winreg.KEY_READ | view) as core:
                    i = 0
                    names = []
                    while True:
                        try:
                            names.append(winreg.EnumKey(core, i))
                        except OSError:
                            break
                        i += 1
            except OSError:
                continue
            for name in names:
                m = _VERSION_KEY.match(name)
                paths = _read_install(hive, view, name) if m else None
                if not paths or not paths[1].is_file():
                    continue
                install_dir, exe = paths
                key = (int(m.group(1)), int(m.group(2)))
                identity = (key, str(install_dir).lower())
                found.setdefault(identity, PythonInstall(f"{key[0]}.{key[1]}", key, install_dir, exe, all_users))
    return sorted(found.values(), key=lambda p: (p.key, p.all_users), reverse=True)


def _norm(entry: str) -> str:
    return os.path.expandvars(entry.strip()).rstrip("\\/").lower()


def _folders(py: PythonInstall, appdata: str) -> List[str]:
    """Every folder a Python puts on PATH: its own, its Scripts, and the
    per-user site folders pip --user uses (`%APPDATA%\\Python\\Python314`...)."""
    tag = f"Python{py.key[0]}{py.key[1]}"
    roaming = Path(appdata) / "Python" / tag
    return [str(py.install_dir), str(py.install_dir / "Scripts"), str(roaming), str(roaming / "Scripts")]


def plan_make_default(machine_path: str, user_path: str, pythons: List[PythonInstall],
                      appdata: Optional[str] = None) -> Optional[PathPlan]:
    """Plan for making the newest of `pythons` the only default. None when
    there are no Pythons to choose from."""
    if not pythons:
        return None
    appdata = appdata if appdata is not None else os.environ.get("APPDATA", "")
    latest = pythons[0]  # installed_pythons() sorts newest first (all-users before per-user)

    keep = {_norm(f) for f in _folders(latest, appdata)[:2]}          # the default's own folders
    drop = set()
    for other in pythons[1:]:
        drop |= {_norm(f) for f in _folders(other, appdata)}
    drop -= keep                                                      # same folder listed twice? keep it

    removed: List[Tuple[str, str]] = []
    scopes = {}
    for scope, raw in (("machine", machine_path), ("user", user_path)):
        entries = [e for e in raw.split(";") if e.strip()]
        kept = []
        for entry in entries:
            n = _norm(entry)
            if n in drop:
                removed.append((scope, entry))
            elif n in keep:
                continue          # re-inserted at the front below
            else:
                kept.append(entry)
        scopes[scope] = kept

    # The default's folders always go to the front of the MACHINE PATH: Windows
    # reads machine entries before user entries, so a per-user Python in the
    # user PATH could never beat any python.exe (MSYS2's, Anaconda's...) that
    # sits on the machine PATH. (Writing it needs elevation - the app has it.)
    target = "machine"
    front = [str(latest.install_dir) + "\\", str(latest.install_dir / "Scripts") + "\\"]
    scopes[target] = front + scopes[target]

    def original(scope_raw: str) -> List[str]:
        return [e for e in scope_raw.split(";") if e.strip()]

    new_machine, new_user = ";".join(scopes["machine"]), ";".join(scopes["user"])
    changed = new_machine != ";".join(original(machine_path)) or new_user != ";".join(original(user_path))
    target_before = original(machine_path if target == "machine" else user_path)
    already_first = [_norm(e) for e in target_before[:2]] == [_norm(f) for f in front]
    added = [] if already_first else [(target, f) for f in front]
    return PathPlan(latest, new_machine, new_user, removed, added, changed)


def apply_plan(plan: PathPlan) -> bool:
    """Writes the planned PATH values (only the scopes that changed)."""
    machine, user = path_backup.read_current_path()
    return path_backup.write_paths(
        plan.new_machine if plan.new_machine != ";".join(e for e in machine.split(";") if e.strip()) else None,
        plan.new_user if plan.new_user != ";".join(e for e in user.split(";") if e.strip()) else None,
    )
