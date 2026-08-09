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
from pathlib import Path
from typing import List, Optional

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


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
    cleaned = _INVALID_FILENAME_CHARS.sub("", name).strip()
    return cleaned or "profile"


def save_profile(app_dir: Path, profile: Profile) -> Path:
    path = profiles_dir(app_dir) / f"{safe_filename(profile.name)}.json"
    path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
    return path


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
