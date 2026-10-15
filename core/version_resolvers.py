"""
Live version/URL resolution against GitHub/Adoptium/nodejs.org APIs, with a
pinned fallback if the API can't be reached: GitHub releases, Adoptium
(Temurin), and the Node.js dist index.

Every resolver returns a LatestInfo so the version shown in the GUI's
"Latest Version" column is exactly the version that will be installed if the
user clicks Install — no separate/divergent version lookup.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

from core import http_cache
from core.logger import get_logger

REQUEST_TIMEOUT = 15
_HEADERS = {"User-Agent": "Runtime-Forge"}


def github_headers() -> dict:
    """Headers for api.github.com ONLY (never send the token to any other
    host). Unauthenticated calls are limited to 60/hour, which a few scans
    exhaust; set GITHUB_TOKEN (or GH_TOKEN) to lift that to 5000/hour."""
    headers = dict(_HEADERS)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

_VERSION_RUN = re.compile(r"\d+(?:[.+]\d+)*")


@dataclass
class LatestInfo:
    version: str
    url: str
    filename: str
    sha256: Optional[str] = None    # from the release API's asset digest, when it offers one


def asset_sha256(asset: dict) -> Optional[str]:
    """GitHub exposes "digest": "sha256:<hex>" on release assets."""
    digest = asset.get("digest") or ""
    return digest.split(":", 1)[1] if digest.startswith("sha256:") else None


def _numeric_tuple(version: str) -> tuple[int, ...]:
    """Extracts the leading run of numeric segments from a version string,
    treating '.' and '+' as equivalent separators — e.g. "21.0.9+10" and
    "jdk-21.0.9.10-hotspot" both normalize to (21, 0, 9, 10), even though
    Adoptium's API and its own installer's folder-naming convention don't
    agree on punctuation for the same version. Returns () if nothing
    numeric is found."""
    match = _VERSION_RUN.search(version)
    if not match:
        return ()
    return tuple(int(part) for part in re.split(r"[.+]", match.group(0)))


def version_is_newer(latest: str, installed: str) -> bool:
    """True only if `latest` is unambiguously newer than `installed`.

    Returns False — not "maybe" — whenever either string can't be parsed
    into a comparable numeric version, so a parsing failure never manifests
    as a false "update available" or an unwanted reinstall. This also
    protects against a stale pinned fallback (used when the version API is
    unreachable) reading as an available "update" that's actually older
    than what's already installed — only a genuinely greater version
    triggers True.
    """
    latest_tuple = _numeric_tuple(latest)
    installed_tuple = _numeric_tuple(installed)
    if not latest_tuple or not installed_tuple:
        return False
    return latest_tuple > installed_tuple


def get_latest_github_asset(
    repo: str, asset_pattern: str, fallback_url: str, fallback_version: str,
    fallback_sha256: Optional[str] = None,
) -> LatestInfo:
    log = get_logger()
    try:
        resp = http_cache.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=github_headers(), timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        rel = resp.json()
        for asset in rel.get("assets", []):
            if asset_pattern.search(asset["name"]):
                return LatestInfo(
                    version=rel["tag_name"].lstrip("v"),
                    url=asset["browser_download_url"],
                    filename=asset["name"],
                    sha256=asset_sha256(asset),
                )
        log.status(f"{repo} latest release had no asset matching pattern; using pinned fallback")
    except Exception as e:
        log.status(f"Could not query GitHub for {repo} latest release ({e}); using pinned fallback")

    return LatestInfo(version=fallback_version, url=fallback_url, filename=fallback_url.rsplit("/", 1)[-1],
                      sha256=fallback_sha256)


def get_latest_node_lts(fallback_version: str, fallback_url: str) -> LatestInfo:
    log = get_logger()
    try:
        resp = http_cache.get("https://nodejs.org/dist/index.json", headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        for row in resp.json():
            if row.get("lts"):
                version = row["version"].lstrip("v")
                return LatestInfo(
                    version=version,
                    url=f"https://nodejs.org/dist/{row['version']}/node-{row['version']}-x64.msi",
                    filename=f"node-{version}-x64.msi",
                )
        log.status("Node.js dist index had no LTS row; using pinned fallback")
    except Exception as e:
        log.status(f"Could not query Node.js dist index ({e}); using pinned fallback")

    return LatestInfo(version=fallback_version, url=fallback_url, filename=fallback_url.rsplit("/", 1)[-1])


_TEMURIN_FILE = re.compile(r"_(\d+(?:\.\d+)*)_(\d+)\.msi$|_(8)u(\d+)b(\d+)\.msi$")


def _temurin_version_from_filename(name: str) -> Optional[str]:
    """OpenJDK21U-...hotspot_21.0.12.1_1.msi -> "21.0.12.1+1";
    OpenJDK8U-...hotspot_8u504b01.msi -> "8.0.504+1"."""
    m = _TEMURIN_FILE.search(name)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}+{m.group(2)}"
    return f"{m.group(3)}.0.{m.group(4)}+{int(m.group(5))}"


def get_latest_temurin(feature_version: int, fallback_version: str) -> LatestInfo:
    """Temurin's MSI from the adoptium/temurin<N>-binaries GitHub release:
    carries a SHA-256 digest, and avoids api.adoptium.net, which resets TLS
    handshakes from Python's OpenSSL on some machines (curl/Schannel are
    fine). Falls back to the Adoptium API if GitHub can't be reached (rate
    limit, offline)."""
    log = get_logger()
    pattern = re.compile(rf"^OpenJDK{feature_version}U-jdk_x64_windows_hotspot_.*\.msi$")
    try:
        resp = http_cache.get(
            f"https://api.github.com/repos/adoptium/temurin{feature_version}-binaries/releases/latest",
            headers=github_headers(), timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if pattern.search(asset["name"]):
                version = _temurin_version_from_filename(asset["name"])
                if version:
                    return LatestInfo(version=version, url=asset["browser_download_url"],
                                      filename=asset["name"], sha256=asset_sha256(asset))
        log.status(f"temurin{feature_version}-binaries latest release had no matching MSI; trying the Adoptium API")
    except Exception as e:
        log.status(f"Could not query GitHub for Temurin {feature_version} ({e}); trying the Adoptium API")
    return get_latest_adoptium(feature_version, fallback_version)


def get_latest_adoptium(feature_version: int, fallback_version: str) -> LatestInfo:
    """Fallback when Temurin's GitHub releases can't be read. The download URL is
    the /installer/latest/... redirect endpoint; for the GUI's version column
    we additionally query /assets/latest (same API family) to surface the
    actual patch version being installed."""
    log = get_logger()
    install_url = (
        f"https://api.adoptium.net/v3/installer/latest/{feature_version}/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk"
    )
    filename = f"temurin-jdk-{feature_version}.msi"
    version = fallback_version
    try:
        resp = http_cache.get(
            f"https://api.adoptium.net/v3/assets/latest/{feature_version}/hotspot"
            "?image_type=jdk&os=windows&architecture=x64",
            headers=_HEADERS, timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        assets = resp.json()
        if assets:
            v = assets[0]["version"]
            version = f"{v['major']}.{v['minor']}.{v['security']}+{v['build']}"
    except Exception as e:
        log.status(f"Could not query Adoptium latest for JDK {feature_version} ({e}); version display uses fallback")

    return LatestInfo(version=version, url=install_url, filename=filename)
