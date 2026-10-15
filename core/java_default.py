"""
Which Java does `java` mean? The same problem as Python (see core/python_default.py):
every Temurin JDK/JRE adds its own `bin` folder to the machine PATH, so with
several installed, `java` is whichever was installed last - e.g. updating JDK 8
silently made `java -version` print 1.8 again.

This discovers the Temurin installs under Program Files\\Eclipse Adoptium and
plans a change that leaves the newest JDK as the default: its `bin` first on
the machine PATH, every other Temurin JDK/JRE `bin` off PATH, and - only if
JAVA_HOME is already set to one of those Temurin folders - JAVA_HOME pointing at
the newest JDK (a JRE there breaks Gradle, Maven and most IDEs). The other JDKs
stay installed; point a tool at one with JAVA_HOME or its full path.

planning is pure (`plan_make_default`) so it can be previewed and tested.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core import path_backup

ADOPTIUM_ROOT = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eclipse Adoptium"


@dataclass(frozen=True)
class JavaInstall:
    name: str            # "jdk-21.0.12.8-hotspot"
    key: Tuple[int, ...]  # (21, 0, 12, 8)
    home: Path
    is_jdk: bool

    @property
    def label(self) -> str:
        return self.name


@dataclass
class JavaPlan:
    latest: JavaInstall
    new_machine: str
    new_user: str
    java_home_machine: Optional[str] = None     # new value, or None = leave alone
    java_home_user: Optional[str] = None
    removed: List[Tuple[str, str]] = field(default_factory=list)
    added: List[Tuple[str, str]] = field(default_factory=list)
    changed: bool = False


def installed_javas(root: Optional[Path] = None) -> List[JavaInstall]:
    """Temurin JDKs and JREs, newest JDK first."""
    base = Path(root) if root is not None else ADOPTIUM_ROOT
    found: List[JavaInstall] = []
    if base.is_dir():
        for child in base.iterdir():
            m = re.match(r"^(jdk|jre)-", child.name)
            if m and child.is_dir() and (child / "bin" / "java.exe").is_file():
                found.append(JavaInstall(child.name, tuple(int(n) for n in re.findall(r"\d+", child.name)), child, m.group(1) == "jdk"))
    return sorted(found, key=lambda j: (j.is_jdk, j.key), reverse=True)


def _norm(entry: str) -> str:
    return os.path.expandvars(entry.strip()).rstrip("\\/").lower()


def plan_make_default(machine_path: str, user_path: str, javas: List[JavaInstall],
                      machine_java_home: Optional[str] = None, user_java_home: Optional[str] = None,
                      root: Optional[Path] = None) -> Optional[JavaPlan]:
    jdks = [j for j in javas if j.is_jdk]
    if not jdks:
        return None
    latest = jdks[0]
    base = _norm(str(root if root is not None else ADOPTIUM_ROOT))

    keep = _norm(str(latest.home / "bin"))
    drop = {_norm(str(j.home / "bin")) for j in javas if j.home != latest.home}
    drop.discard(keep)

    removed: List[Tuple[str, str]] = []
    scopes = {}
    for scope, raw in (("machine", machine_path), ("user", user_path)):
        kept = []
        for entry in (e for e in raw.split(";") if e.strip()):
            n = _norm(entry)
            if n in drop:
                removed.append((scope, entry))
            elif n != keep:
                kept.append(entry)
        scopes[scope] = kept

    front = str(latest.home / "bin")
    scopes["machine"] = [front] + scopes["machine"]
    original = [e for e in machine_path.split(";") if e.strip()]
    already_first = bool(original) and _norm(original[0]) == keep
    added = [] if already_first else [("machine", front)]

    def repoint(current: Optional[str]) -> Optional[str]:
        """New JAVA_HOME if it currently points into the Temurin folder at a different install."""
        if not current:
            return None
        n = _norm(current)
        if n.startswith(base) and n != _norm(str(latest.home)):
            return str(latest.home)
        return None

    home_machine, home_user = repoint(machine_java_home), repoint(user_java_home)
    new_machine, new_user = ";".join(scopes["machine"]), ";".join(scopes["user"])
    path_changed = new_machine != ";".join(original) or new_user != ";".join(e for e in user_path.split(";") if e.strip())
    return JavaPlan(latest, new_machine, new_user, home_machine, home_user, removed, added,
                    changed=path_changed or home_machine is not None or home_user is not None)


def apply_plan(plan: JavaPlan) -> bool:
    machine, user = path_backup.read_current_path()
    ok = path_backup.write_paths(
        plan.new_machine if plan.new_machine != ";".join(e for e in machine.split(";") if e.strip()) else None,
        plan.new_user if plan.new_user != ";".join(e for e in user.split(";") if e.strip()) else None,
    )
    if plan.java_home_machine is not None:
        ok = path_backup.write_env_var("machine", "JAVA_HOME", plan.java_home_machine) and ok
    if plan.java_home_user is not None:
        ok = path_backup.write_env_var("user", "JAVA_HOME", plan.java_home_user) and ok
    return ok
