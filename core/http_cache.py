"""
Cache for the read-only "what's the latest version" GETs, in two layers.

**In memory, per run.** A scan resolves ~40 components concurrently and
several share an endpoint (nine .NET components read one releases-index.json);
installing then resolves the same components again. Concurrent callers for one
URL share a single in-flight request (single-flight).

**On disk, across runs (optional - see configure_disk_cache).** GitHub's
unauthenticated limit is 60 requests an hour and a single scan uses ~20, so a
couple of rescans used to leave every lookup failing with HTTP 403 and the app
guessing from pinned versions. Responses are now stored with their ETag:
  - a repeat request is conditional (If-None-Match); GitHub answers 304 and
    doesn't count it against the limit;
  - if the request fails *or is rate limited*, the last good copy is served
    instead of nothing, however old (a slightly stale "latest" beats none).

Not for downloads - those stream large files and go through core.downloader.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from core.logger import get_logger

DEFAULT_TTL = 15 * 60        # successful responses, in memory
FAILURE_TTL = 60             # HTTP errors (e.g. a 403 rate limit): don't hammer
ERROR_TTL = 30               # connection errors
MAX_DISK_BODY = 2 * 1024 * 1024
_DISK_HOSTS = ("https://api.github.com/", "https://raw.githubusercontent.com/", "https://go.dev/", "https://static.rust-lang.org/",
               "https://update.code.visualstudio.com/", "https://builds.dotnet.microsoft.com/",
               "https://nodejs.org/", "https://vulkan.lunarg.com/")

_lock = threading.Lock()
_entries: Dict[tuple, Tuple[float, object]] = {}   # key -> (expires_at, Response | Exception)
_key_locks: Dict[tuple, threading.Lock] = {}

_disk_path: Optional[Path] = None
_disk: Dict[str, dict] = {}                        # url -> {"etag", "body", "saved"}
_disk_dirty = False


class StoredResponse:
    """A response rebuilt from the on-disk copy; quacks like requests.Response
    for the bits the resolvers use."""
    status_code = 200
    ok = True
    from_cache = True

    def __init__(self, url: str, body: str):
        self.url, self.text = url, body
        self.headers: dict = {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        return None


def configure_disk_cache(path: Optional[Path]) -> None:
    """Turn the persistent layer on (or off with None). Safe to call again."""
    global _disk_path, _disk, _disk_dirty
    with _lock:
        _disk_path, _disk, _disk_dirty = path, {}, False
        if path is None:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _disk = {u: e for u, e in data.items() if isinstance(e, dict) and isinstance(e.get("body"), str)}
        except (OSError, ValueError):
            _disk = {}


def flush() -> None:
    """Write the on-disk layer if anything changed (called when a scan ends and on exit)."""
    global _disk_dirty
    with _lock:
        if _disk_path is None or not _disk_dirty:
            return
        snapshot = dict(_disk)
        _disk_dirty = False
        path = _disk_path
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def clear() -> None:
    """Forget the in-memory layer - a user-requested Rescan should look again.
    (The on-disk copies stay: they're what keeps a rate-limited rescan working.)"""
    with _lock:
        _entries.clear()


def _lookup(key: tuple):
    with _lock:
        entry = _entries.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _disk_entry(url: str) -> Optional[dict]:
    with _lock:
        return _disk.get(url) if _disk_path is not None else None


def _remember(url: str, resp: requests.Response) -> None:
    global _disk_dirty
    if _disk_path is None or not url.startswith(_DISK_HOSTS) or len(resp.content) > MAX_DISK_BODY:
        return
    with _lock:
        _disk[url] = {"etag": resp.headers.get("ETag"), "body": resp.text, "saved": time.time()}
        _disk_dirty = True


def get(url: str, headers: Optional[dict] = None, timeout: float = 15, ttl: float = DEFAULT_TTL):
    """requests.get() with caching. Returns the (possibly cached) response -
    callers still call raise_for_status()/json()/text as usual. Raises whatever
    the original request raised (also cached briefly) unless an older copy is
    on disk to fall back to."""
    # Credentials are part of the key so an authenticated response is never
    # served to (or hidden from) a differently-authenticated caller.
    key = (url, (headers or {}).get("Authorization"))
    cached = _lookup(key)
    if cached is not None:
        if isinstance(cached, Exception):
            raise cached
        return cached

    with _lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        cached = _lookup(key)       # another thread may have filled it while we waited
        if cached is not None:
            if isinstance(cached, Exception):
                raise cached
            return cached

        stored = _disk_entry(url)
        request_headers = dict(headers or {})
        if stored and stored.get("etag"):
            request_headers["If-None-Match"] = stored["etag"]
        try:
            resp = requests.get(url, headers=request_headers or None, timeout=timeout)
        except requests.RequestException as e:
            if stored:
                return _serve_stored(key, url, stored, f"{type(e).__name__}")
            with _lock:
                _entries[key] = (time.monotonic() + ERROR_TTL, e)
            raise

        if resp.status_code == 304 and stored:
            return _serve_stored(key, url, stored, None)
        if resp.ok:
            _remember(url, resp)
            with _lock:
                _entries[key] = (time.monotonic() + ttl, resp)
            return resp
        if stored:  # rate limited / server error: an old answer beats no answer
            return _serve_stored(key, url, stored, f"HTTP {resp.status_code}")
        with _lock:
            _entries[key] = (time.monotonic() + FAILURE_TTL, resp)
        return resp


def _serve_stored(key: tuple, url: str, stored: dict, reason: Optional[str]) -> StoredResponse:
    if reason:
        age_h = (time.time() - stored.get("saved", 0)) / 3600
        get_logger().status(f"Using the saved copy of {url} ({reason}; saved {age_h:.0f}h ago)")
    response = StoredResponse(url, stored["body"])
    with _lock:
        _entries[key] = (time.monotonic() + DEFAULT_TTL, response)
    return response
