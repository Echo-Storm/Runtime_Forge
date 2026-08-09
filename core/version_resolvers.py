"""
Live version/URL resolution against GitHub/Adoptium/nodejs.org APIs, with a
pinned fallback if the API can't be reached — ported from
Get-LatestGitHubAsset in ALLTHERUNTIMES.ps1, plus equivalents for Adoptium
and the Node.js dist index (which the PS1 queries inline rather than through
a shared helper).

Every resolver returns a LatestInfo so the version shown in the GUI's
"Latest Version" column is exactly the version that will be installed if the
user clicks Install — no separate/divergent version lookup.
"""

from dataclasses import dataclass
from typing import Optional

import requests

from core.logger import get_logger

REQUEST_TIMEOUT = 15
_HEADERS = {"User-Agent": "AIO-Runtime-Installer"}


@dataclass
class LatestInfo:
    version: str
    url: str
    filename: str


def get_latest_github_asset(
    repo: str, asset_pattern: str, fallback_url: str, fallback_version: str
) -> LatestInfo:
    log = get_logger()
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers=_HEADERS, timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        rel = resp.json()
        for asset in rel.get("assets", []):
            if asset_pattern.search(asset["name"]):
                return LatestInfo(
                    version=rel["tag_name"].lstrip("v"),
                    url=asset["browser_download_url"],
                    filename=asset["name"],
                )
        log.status(f"{repo} latest release had no asset matching pattern; using pinned fallback")
    except Exception as e:
        log.status(f"Could not query GitHub for {repo} latest release ({e}); using pinned fallback")

    return LatestInfo(version=fallback_version, url=fallback_url, filename=fallback_url.rsplit("/", 1)[-1])


def get_latest_node_lts(fallback_version: str, fallback_url: str) -> LatestInfo:
    log = get_logger()
    try:
        resp = requests.get("https://nodejs.org/dist/index.json", headers=_HEADERS, timeout=REQUEST_TIMEOUT)
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


def get_latest_adoptium(feature_version: int, fallback_version: str) -> LatestInfo:
    """The PS1 uses the /installer/latest/... redirect endpoint directly as
    the download URL without inspecting the resolved version. For the GUI's
    version column we additionally query the /assets/latest endpoint (same
    API family) to surface the actual patch version being installed."""
    log = get_logger()
    install_url = (
        f"https://api.adoptium.net/v3/installer/latest/{feature_version}/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk"
    )
    filename = f"temurin-jdk-{feature_version}.msi"
    version = fallback_version
    try:
        resp = requests.get(
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
