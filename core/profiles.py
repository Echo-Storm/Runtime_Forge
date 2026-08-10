"""
Named selection presets ("profiles") — a saved list of component keys so a
machine-specific selection (e.g. "Game Dev Machine", "Fresh Windows Setup")
can be reapplied in one click instead of re-checking two dozen boxes by
hand, or carried to a new machine entirely via Export/Import.

Stored as portable JSON next to the exe (app_dir/profiles/*.json), same
philosophy as settings/logs elsewhere in this app — nothing touches the
registry, the whole folder is what you'd copy to bring profiles along.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

# A general "make sure this Windows machine can run old and new software"
# baseline — broad compatibility/runtime coverage, deliberately excluding
# role-specific dev tooling (Java, Python, Git, Node, CMake, VS Code,
# PowerShell). There's no universal answer for which of those any given
# person wants, but VC++/.NET/DirectX/OpenAL/WebView2 coverage is close to
# always-useful regardless of what the machine is actually for.
DEFAULT_PROFILE_NAME = "Basic"
_DEFAULT_PROFILE_CATEGORIES = {"Core Runtimes", "VC++ Redistributables", ".NET Runtimes"}

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass
class Profile:
    name: str
    component_keys: List[str] = field(default_factory=list)
    created: str = ""  # ISO timestamp string, stamped by the caller


def profiles_dir(app_dir: Path) -> Path:
    d = app_dir / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_filename(name: str) -> str:
    # Windows silently rejects a handful of names regardless of extension
    # (CON.json is exactly as invalid as CON) and always strips trailing
    # dots/spaces from what's asked for — without handling both, a profile
    # named "CON" or ending in a space/dot reaches path.write_text() and
    # raises an uncaught OSError on an entirely ordinary "type a name" action.
    cleaned = _INVALID_FILENAME_CHARS.sub("", name).strip().rstrip(". ")
    if not cleaned:
        return "profile"
    # Windows matches reserved device names against the segment before the
    # *first* dot, not the whole filename — "PRN.json" is exactly as
    # blocked as "PRN" (and would become "PRN.json.json" once save_profile
    # appends its own ".json", still leading with the same blocked segment).
    if cleaned.split(".", 1)[0].upper() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_profile"
    return cleaned


def save_profile(app_dir: Path, profile: Profile) -> Optional[Path]:
    path = profiles_dir(app_dir) / f"{safe_filename(profile.name)}.json"
    try:
        path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        return path
    except OSError:
        return None


def load_profile(path: Path) -> Optional[Profile]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Profile(
            name=str(data.get("name") or path.stem),
            component_keys=[str(k) for k in data.get("component_keys", [])],
            created=str(data.get("created", "")),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def list_profiles(app_dir: Path) -> List[Profile]:
    found = []
    for path in sorted(profiles_dir(app_dir).glob("*.json")):
        profile = load_profile(path)
        if profile:
            found.append(profile)
    return found


def delete_profile(app_dir: Path, name: str) -> bool:
    path = profiles_dir(app_dir) / f"{safe_filename(name)}.json"
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def export_profile(profile: Profile, dest_path: Path) -> bool:
    try:
        dest_path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def default_basic_profile(components: Iterable) -> Profile:
    """Built from live Component objects (duck-typed: anything with .key
    and .category), not a static list of key strings — stays correct
    automatically if a component gets renamed or a category's membership
    changes, instead of silently drifting out of sync with the registry."""
    keys = [c.key for c in components if c.category in _DEFAULT_PROFILE_CATEGORIES]
    return Profile(name=DEFAULT_PROFILE_NAME, component_keys=keys, created=datetime.now().isoformat(timespec="seconds"))


def ensure_default_profile(app_dir: Path, components: Iterable) -> None:
    """Seeds a "Basic" profile on first run only — if profiles/ already has
    anything in it (including a user-renamed-away-from "Basic" one), this
    does nothing. Never overwrites or competes with what someone's actually
    built."""
    if list_profiles(app_dir):
        return
    save_profile(app_dir, default_basic_profile(components))
