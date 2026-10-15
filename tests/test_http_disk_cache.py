"""
Tests for core/http_cache's persistent layer: ETag revalidation, serving the
last good copy when a request is rate limited or fails, and surviving a restart.

Run directly:
    venv\\Scripts\\python.exe tests\\test_http_disk_cache.py
"""

import http.server
import json
import sys
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import http_cache
from core.logger import setup_logging

tmp = Path(tempfile.mkdtemp(prefix="rf_diskcache_"))
setup_logging(tmp)
results = {}

state = {"mode": "ok", "hits": 0, "conditional_hits": 0, "body": {"tag_name": "v1.0"}}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        state["hits"] += 1
        etag = '"abc"'
        if self.headers.get("If-None-Match") == etag:
            state["conditional_hits"] += 1
        if state["mode"] == "limited":
            body = b'{"message": "rate limit exceeded"}'
            self.send_response(403)
        elif state["mode"] == "ok" and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        else:
            body = json.dumps(state["body"]).encode()
            self.send_response(200)
        self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"
url = f"{base}/repos/o/r/releases/latest"
http_cache._DISK_HOSTS = (base,)     # allow the local server onto the disk layer

cache_file = tmp / "http_cache.json"
http_cache.configure_disk_cache(cache_file)
http_cache.clear()

# first fetch: 200, stored
r = http_cache.get(url)
results["first_fetch_returns_the_body"] = r.json() == {"tag_name": "v1.0"}
http_cache.flush()
results["flush_writes_the_cache_file"] = cache_file.is_file() and url in json.loads(cache_file.read_text())
results["etag_is_stored"] = json.loads(cache_file.read_text())[url]["etag"] == '"abc"'

# a rescan (memory cleared): conditional request, 304 -> stored copy
http_cache.clear()
before = state["hits"]
r = http_cache.get(url)
results["rescan_sends_if_none_match"] = state["conditional_hits"] == 1
results["304_serves_the_stored_body"] = r.json() == {"tag_name": "v1.0"} and getattr(r, "from_cache", False)
results["stored_response_behaves_like_a_response"] = r.ok and r.status_code == 200 and r.raise_for_status() is None and "tag_name" in r.text

# rate limited: the last good copy is served instead of a 403
state["mode"] = "limited"
http_cache.clear()
r = http_cache.get(url)
results["rate_limit_falls_back_to_the_saved_copy"] = r.ok and r.json() == {"tag_name": "v1.0"}

# a URL never seen before still reports the failure honestly
http_cache.clear()
fresh = http_cache.get(f"{base}/repos/never/seen/releases/latest")
results["unseen_url_still_reports_the_403"] = fresh.status_code == 403

# server unreachable: saved copy again; unseen URL raises
server.shutdown()
server.server_close()
http_cache.clear()
r = http_cache.get(url, timeout=2)
results["connection_failure_falls_back_to_the_saved_copy"] = r.json() == {"tag_name": "v1.0"}
try:
    http_cache.get(f"{base}/other", timeout=2)
    results["connection_failure_without_a_copy_raises"] = False
except Exception:
    results["connection_failure_without_a_copy_raises"] = True

# survives a restart
http_cache.configure_disk_cache(cache_file)
http_cache.clear()
r = http_cache.get(url, timeout=2)
results["saved_copy_survives_a_restart"] = r.json() == {"tag_name": "v1.0"}

# hosts outside the allowlist never touch the disk
http_cache._DISK_HOSTS = ("https://api.github.com/",)
http_cache.configure_disk_cache(tmp / "other.json")
http_cache._remember("http://elsewhere.test/x", type("R", (), {"content": b"x", "text": "x", "headers": {}})())
http_cache.flush()
results["non_allowlisted_hosts_are_not_persisted"] = not (tmp / "other.json").exists()

# a corrupt file is ignored, not fatal
(tmp / "bad.json").write_text("{not json")
http_cache.configure_disk_cache(tmp / "bad.json")
results["corrupt_cache_file_is_ignored"] = http_cache._disk == {}

http_cache.configure_disk_cache(None)
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
