"""
Download helper, ported from ALLTHERUNTIMES.ps1's Get-File: caches by
filename, retries up to 3 times with a 5-second delay, and rejects
implausibly small downloads (usually an error/landing page instead of the
real installer) as a sanity check that a request exception alone wouldn't
catch.
"""

import time
from pathlib import Path
from typing import Callable, Optional

import requests

from core.logger import get_logger

MIN_PLAUSIBLE_BYTES = 10 * 1024
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
CHUNK_SIZE = 1024 * 256

ProgressCB = Optional[Callable[[str, float], None]]


def download(
    url: str,
    dest_dir: Path,
    filename: str,
    name: str,
    dry_run: bool = False,
    progress_cb: ProgressCB = None,
) -> Optional[Path]:
    """Downloads `url` to `dest_dir/filename`. Returns the path on success,
    or None if every attempt failed. In dry-run mode, logs what would happen
    and returns the would-be path without touching the network or disk."""
    log = get_logger()
    dest_path = dest_dir / filename

    if dry_run:
        log.dry(f"Would download: {filename}  <-  {url}")
        return dest_path

    if dest_path.is_file():
        # A prior run killed mid-download (crash, power loss, a hard kill —
        # temp_installers/ is only cleaned up at the end of a *completed*
        # InstallWorker run, so a truncated file can genuinely survive to
        # the next launch) would otherwise be trusted as-is here, with none
        # of the size-sanity check the fresh-download path below enforces —
        # handing a corrupt installer straight to run_exe/run_msi.
        if dest_path.stat().st_size >= MIN_PLAUSIBLE_BYTES:
            log.status(f"Cached: {filename}")
            return dest_path
        log.status(f"Cached file for {filename} looks truncated - re-downloading")
        dest_path.unlink(missing_ok=True)

    log.status(f"Downloading {filename}...")
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Runtime-Forge"}) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0)) or None
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb and total:
                            progress_cb(f"Downloading {name}...", downloaded / total)

            size = dest_path.stat().st_size
            if size < MIN_PLAUSIBLE_BYTES:
                raise ValueError(f"Downloaded file is implausibly small ({size} bytes) - likely not the real installer")

            log.success(f"Downloaded: {filename}")
            return dest_path

        except Exception as e:
            log.fail(f"Attempt {attempt} failed: {e}")
            dest_path.unlink(missing_ok=True)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

    log.fail(f"Download failed after {RETRY_ATTEMPTS} attempts: {filename}")
    return None
