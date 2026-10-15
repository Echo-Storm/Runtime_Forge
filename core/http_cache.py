"""
Small in-process cache for the read-only "what's the latest version" GETs.

A scan resolves ~30 components concurrently, and several share an endpoint
(nine .NET components read the same releases-index.json); installing then
resolves the same components again. Without this each of those is its own
request, and GitHub's unauthenticated limit is only 60 per hour. Concurrent
callers for the same URL share one in-flight request (single-flight).

Not for downloads - those stream large files and go through
core.downloader.
"""

import threading
import time
from typing import Dict, Optional, Tuple

import requests

DEFAULT_TTL = 15 * 60        # successful responses
FAILURE_TTL = 60             # HTTP errors (e.g. a 403 rate limit): don't hammer
ERROR_TTL = 30               # connection errors

_lock = threading.Lock()
_entries: Dict[tuple, Tuple[float, object]] = {}   # key -> (expires_at, Response | Exception)
_key_locks: Dict[tuple, threading.Lock] = {}


def clear() -> None:
    """Forget everything - a user-requested Rescan should see fresh data."""
    with _lock:
        _entries.clear()


def _lookup(key: tuple):
    with _lock:
        entry = _entries.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def get(url: str, headers: Optional[dict] = None, timeout: float = 15, ttl: float = DEFAULT_TTL) -> requests.Response:
    """requests.get() with caching. Returns the (possibly cached) Response -
    callers still call raise_for_status()/json() as usual. Raises whatever the
    original request raised, also cached briefly."""
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
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            with _lock:
                _entries[key] = (time.monotonic() + ERROR_TTL, e)
            raise
        with _lock:
            _entries[key] = (time.monotonic() + (ttl if resp.ok else FAILURE_TTL), resp)
        return resp
