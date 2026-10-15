"""
Merging the bundled Windows Terminal profile into a user's settings.json
instead of replacing the file.

The bundled settings carry this app's profiles (identified by GUID), its colour
schemes, and a few defaults. Applying them used to overwrite settings.json
wholesale (with a backup), which discarded anything the user had added since.
Now:

  * the user's own profiles, schemes, actions, keybindings, theme... stay;
  * each bundled profile replaces the user's profile with the same GUID (so a
    reapply refreshes it) or is appended - except that the user's own
    show/hide choice (`hidden`) for it is kept;
  * schemes are matched by name the same way;
  * `profiles.defaults` and the top-level settings only ever FILL IN keys the
    user doesn't have - existing values are never changed.

Windows Terminal's settings.json is JSON *with comments and trailing commas*,
so reading it goes through a small tolerant parser. (Comments are not kept
when the merged file is written - the timestamped backup next to the file has
them.)
"""

import copy
import json
from typing import Any, Dict, List

_TOP_LEVEL_FILL_ONLY = ("$help", "$schema", "defaultProfile", "newTabMenu", "actions", "keybindings", "themes")


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, leaving strings intact."""
    out: List[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "/" and text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1

    # trailing commas: a comma whose next significant character closes a container
    cleaned = "".join(out)
    result: List[str] = []
    in_string = False
    i, n = 0, len(cleaned)
    while i < n:
        c = cleaned[i]
        if in_string:
            result.append(c)
            if c == "\\" and i + 1 < n:
                result.append(cleaned[i + 1])
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            result.append(c)
        elif c == ",":
            j = i + 1
            while j < n and cleaned[j] in " \t\r\n":
                j += 1
            if j < n and cleaned[j] in "}]":
                i += 1
                continue
            result.append(c)
        else:
            result.append(c)
        i += 1
    return "".join(result)


def parse_settings(text: str) -> Dict[str, Any]:
    """Parse a settings.json (comments / trailing commas / BOM allowed). Raises ValueError."""
    data = json.loads(strip_jsonc(text.lstrip("﻿")))
    if not isinstance(data, dict):
        raise ValueError("settings.json isn't a JSON object")
    return data


def _profile_list(settings: Dict[str, Any]) -> List[dict]:
    profiles = settings.get("profiles")
    if isinstance(profiles, list):          # the old, pre-1.0 layout
        return [p for p in profiles if isinstance(p, dict)]
    if isinstance(profiles, dict) and isinstance(profiles.get("list"), list):
        return [p for p in profiles["list"] if isinstance(p, dict)]
    return []


def _guid(profile: dict) -> str:
    return str(profile.get("guid", "")).lower()


def merge(user: Dict[str, Any], bundled: Dict[str, Any]) -> Dict[str, Any]:
    """The user's settings with the bundled profiles, schemes and defaults applied (see module docstring)."""
    out = copy.deepcopy(user)

    profiles = out.get("profiles")
    if isinstance(profiles, list):
        profiles = {"list": profiles}
    if not isinstance(profiles, dict):
        profiles = {}
    out["profiles"] = profiles
    plist = profiles.setdefault("list", [])

    index = {_guid(p): i for i, p in enumerate(plist) if isinstance(p, dict)}
    for ours in _profile_list(bundled):
        mine = copy.deepcopy(ours)
        position = index.get(_guid(ours))
        if position is None:
            plist.append(mine)
            index[_guid(ours)] = len(plist) - 1
            continue
        if "hidden" in plist[position]:
            mine["hidden"] = plist[position]["hidden"]      # their show/hide choice wins
        plist[position] = mine

    defaults = profiles.setdefault("defaults", {})
    for key, value in (bundled.get("profiles", {}).get("defaults") or {}).items():
        defaults.setdefault(key, copy.deepcopy(value))

    schemes = out.setdefault("schemes", [])
    by_name = {str(s.get("name", "")).lower(): i for i, s in enumerate(schemes) if isinstance(s, dict)}
    for scheme in bundled.get("schemes", []):
        position = by_name.get(str(scheme.get("name", "")).lower())
        if position is None:
            schemes.append(copy.deepcopy(scheme))
        else:
            schemes[position] = copy.deepcopy(scheme)

    for key in _TOP_LEVEL_FILL_ONLY:
        if key not in out and key in bundled:
            out[key] = copy.deepcopy(bundled[key])
    return out


def _same(a: dict, b: dict) -> bool:
    """Equal, ignoring the user's own show/hide choice."""
    strip = lambda d: {k: v for k, v in d.items() if k != "hidden"}  # noqa: E731
    return strip(a) == strip(b)


def is_applied(user: Dict[str, Any], bundled: Dict[str, Any]) -> bool:
    """True when every bundled profile and scheme is present and current in `user`."""
    mine = {_guid(p): p for p in _profile_list(user)}
    for ours in _profile_list(bundled):
        theirs = mine.get(_guid(ours))
        if theirs is None or not _same(theirs, ours):
            return False
    schemes = {str(s.get("name", "")).lower(): s for s in user.get("schemes", []) if isinstance(s, dict)}
    for scheme in bundled.get("schemes", []):
        theirs = schemes.get(str(scheme.get("name", "")).lower())
        if theirs is None or theirs != scheme:
            return False
    return True
