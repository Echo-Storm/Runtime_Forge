"""
Download helper: caches by filename, retries up to 3 times with a 5-second
delay, rejects implausibly small or truncated downloads (usually an
error/landing page instead of the real installer), and verifies each file's
SHA-256 and/or Authenticode signer before it can be run.
"""

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import requests

from core.logger import get_logger
from core.signature import verify_signature

MIN_PLAUSIBLE_BYTES = 10 * 1024
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
CHUNK_SIZE = 1024 * 256

ProgressCB = Optional[Callable[[str, float], None]]


class IntegrityError(Exception):
    """Hash or signature check failed - deterministic, so never retried."""


@dataclass(frozen=True)
class Trust:
    """What a downloaded file must prove before it's allowed to run.
    `sha256` pins the exact bytes (from the release API's digest, or pinned
    in source for a fixed version); `publishers` requires a valid Authenticode
    signature whose signer name contains one of these strings. Either or both
    may be given; with neither, the file is accepted but logged as unverified."""
    publishers: Tuple[str, ...] = ()
    sha256: Optional[str] = None


# path -> (actual sha256, Trust) for every file that passed download()'s
# checks, so run_exe/run_msi can re-verify the same bytes at the moment of
# execution (the download folder isn't a place to trust between those steps).
_VERIFIED: Dict[str, Tuple[str, Trust]] = {}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify(path: Path, name: str, trust: Optional[Trust]) -> bool:
    log = get_logger()
    actual = file_sha256(path)
    if trust is None or (not trust.sha256 and not trust.publishers):
        log.status(f"WARNING: no integrity check available for {name} - running unverified")
    else:
        if trust.sha256 and actual.lower() != trust.sha256.lower():
            log.fail(f"{name}: SHA-256 mismatch (expected {trust.sha256[:16]}..., got {actual[:16]}...)")
            return False
        if trust.sha256:
            log.status(f"SHA-256 OK: {name}")
        if trust.publishers and not verify_signature(str(path), name, trust.publishers):
            return False
    _VERIFIED[str(path)] = (actual, trust or Trust())
    return True


def reverify(path: Path, name: str) -> Optional[bool]:
    """Re-checks a file previously accepted by download(), right before it's
    executed. None if the file never went through download() (caller decides
    what to do); False if it changed or no longer verifies."""
    record = _VERIFIED.get(str(path))
    if record is None:
        return None
    actual, trust = record
    log = get_logger()
    if file_sha256(path) != actual:
        log.fail(f"{name}: file changed on disk after it was verified - refusing to run it")
        return False
    if trust.publishers and not verify_signature(str(path), name, trust.publishers):
        return False
    return True


def download(
    url: str,
    dest_dir: Path,
    filename: str,
    name: str,
    dry_run: bool = False,
    progress_cb: ProgressCB = None,
    trust: Optional[Trust] = None,
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
        if dest_path.stat().st_size >= MIN_PLAUSIBLE_BYTES and _verify(dest_path, name, trust):
            log.status(f"Cached: {filename}")
            return dest_path
        log.status(f"Cached file for {filename} is truncated or failed verification - re-downloading")
        dest_path.unlink(missing_ok=True)

    log.status(f"Downloading {filename}...")
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Runtime-Forge"}) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0)) or None
                # Content-Length counts the encoded bytes; a gzip'd body decodes
                # to a different size, so only verify length for identity encoding.
                verify_len = total if not resp.headers.get("Content-Encoding") else None
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
            if verify_len and size != verify_len:
                raise ValueError(f"Download truncated ({size} of {verify_len} bytes)")
            if size < MIN_PLAUSIBLE_BYTES:
                raise ValueError(f"Downloaded file is implausibly small ({size} bytes) - likely not the real installer")

            if not _verify(dest_path, name, trust):
                raise IntegrityError("downloaded file failed integrity verification")

            log.success(f"Downloaded: {filename}")
            return dest_path

        except IntegrityError as e:
            log.fail(f"{name}: {e} - discarding the file, not retrying")
            dest_path.unlink(missing_ok=True)
            _VERIFIED.pop(str(dest_path), None)
            return None
        except Exception as e:
            log.fail(f"Attempt {attempt} failed: {e}")
            dest_path.unlink(missing_ok=True)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

    log.fail(f"Download failed after {RETRY_ATTEMPTS} attempts: {filename}")
    return None
