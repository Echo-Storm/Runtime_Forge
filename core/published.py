"""
The published version catalog: `data/versions.json` in this repo, refreshed
daily by .github/workflows/update-versions.yml.

Why it exists: a scan used to ask api.github.com about ~20 projects, and
GitHub's unauthenticated limit is 60 requests an hour - a couple of scans and
every lookup failed, so the app guessed from pinned versions. The catalog is
ONE request to raw.githubusercontent.com (a CDN with no such limit) that
carries, for every GitHub-hosted component, the latest version, the download
URL and the SHA-256 GitHub publishes for it.

Rules the app applies to it:
  * it is consulted first, and the live API is the fallback - unless a
    GITHUB_TOKEN/GH_TOKEN is set, in which case live (exact, and fast enough
    with a token) wins (RUNTIME_FORGE_NO_CATALOG=1 also skips it);
  * an entry must be well-formed, point at https://github.com/, and its file
    name must match the pattern the component expects, or it is ignored;
  * a catalog older than MAX_AGE_DAYS is ignored (CI stopped?) rather than served;
  * any failure just means "no catalog" - nothing here can break a scan.
Downloads are verified exactly as before (publisher signature and/or SHA-256),
so the catalog only ever *selects* a version; it can't make an unverified file run.
"""

import datetime
import os
import re
from typing import Dict, Optional

from core import http_cache

CATALOG_URL = "https://raw.githubusercontent.com/Echo-Storm/Runtime_Forge/main/data/versions.json"
SCHEMA = 1
MAX_AGE_DAYS = 10

# component key -> GitHub repo whose latest release it installs
REPOS: Dict[str, str] = {
    "openal": "kcat/openal-soft",
    "winget": "microsoft/winget-cli",
    "pwsh": "PowerShell/PowerShell",
    "git": "git-for-windows/git",
    "cmake": "Kitware/CMake",
    "gh": "cli/cli",
    "llvm": "llvm/llvm-project",
    "ninja": "ninja-build/ninja",
    "jq": "jqlang/jq",
    "terminal": "microsoft/terminal",
    "uv": "astral-sh/uv",
    "ghidra": "NationalSecurityAgency/ghidra",
    "jdk_21": "adoptium/temurin21-binaries",
    "jdk_17": "adoptium/temurin17-binaries",
    "jdk_8": "adoptium/temurin8-binaries",
}

_disabled = False
_strict = False
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def disable() -> None:
    """Never consult the catalog (the generator, and tests that want the live path)."""
    global _disabled
    _disabled = True


def enable() -> None:
    global _disabled
    _disabled = False


def set_strict(on: bool) -> None:
    """Strict mode (the generator): resolvers must raise instead of falling
    back to a pinned version, so a stale pin is never published as 'latest'."""
    global _strict
    _strict = on


def is_strict() -> bool:
    return _strict


def _has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


def _load() -> Optional[dict]:
    try:
        resp = http_cache.get(CATALOG_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 - offline, 404 before the first run, bad JSON...
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("entries"), dict):
        return None
    try:
        generated = datetime.date.fromisoformat(str(data.get("generated", ""))[:10])
    except ValueError:
        return None
    if (datetime.date.today() - generated).days > MAX_AGE_DAYS:
        return None
    return data


def lookup(repo: str, filename_pattern: Optional["re.Pattern[str]"] = None):
    """The published LatestInfo for `repo`, or None (use the live API)."""
    from core.version_resolvers import LatestInfo   # imported late: version_resolvers imports this module

    if _disabled or _strict or _has_token() or os.environ.get("RUNTIME_FORGE_NO_CATALOG") == "1":
        return None
    data = _load()
    entry = data["entries"].get(repo) if data else None
    if not isinstance(entry, dict):
        return None
    version, url, filename, sha = (entry.get(k) for k in ("version", "url", "filename", "sha256"))
    if not all(isinstance(v, str) and v for v in (version, url, filename)):
        return None
    if not url.startswith("https://github.com/"):
        return None
    if sha is not None and not (isinstance(sha, str) and _HEX64.match(sha)):
        return None
    if filename_pattern is not None and not filename_pattern.search(filename):
        return None
    return LatestInfo(version=version, url=url, filename=filename, sha256=sha.lower() if sha else None)
