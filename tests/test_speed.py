"""
Tests for the scan-speed work: the shared HTTP cache (single-flight, TTL,
failure caching) and the one-read registry snapshot.

Run directly:
    venv\\Scripts\\python.exe tests\\test_speed.py
"""

import http.server
import re
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import checks, http_cache

results = {}

# ---- HTTP cache against a local server that counts hits
hits = {"ok": 0, "slow": 0, "denied": 0}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].strip("/")
        hits[path] = hits.get(path, 0) + 1
        if path == "slow":
            time.sleep(0.3)
        status = 403 if path == "denied" else 200
        body = b'{"n": 1}'
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"

http_cache.clear()
a = http_cache.get(f"{base}/ok")
b = http_cache.get(f"{base}/ok")
results["second_get_served_from_cache"] = hits["ok"] == 1 and a is b and a.json() == {"n": 1}

# many threads asking for the same URL at once share ONE request
threads = [threading.Thread(target=http_cache.get, args=(f"{base}/slow",)) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
results["concurrent_callers_share_one_request"] = hits["slow"] == 1

# an HTTP error is cached too, so a rate limit isn't hammered
r1 = http_cache.get(f"{base}/denied")
r2 = http_cache.get(f"{base}/denied")
results["http_error_cached_briefly"] = hits["denied"] == 1 and r1.status_code == 403 and r2 is r1

# different credentials never share an entry
http_cache.get(f"{base}/ok", headers={"Authorization": "Bearer x"})
results["authorization_is_part_of_the_key"] = hits["ok"] == 2

http_cache.clear()
http_cache.get(f"{base}/ok")
results["clear_forces_refetch"] = hits["ok"] == 3

# expiry
http_cache.clear()
http_cache.get(f"{base}/ok", ttl=0.05)
time.sleep(0.1)
http_cache.get(f"{base}/ok", ttl=0.05)
results["ttl_expiry_refetches"] = hits["ok"] == 5

# a connection error is raised each time (and cached briefly)
dead = "http://127.0.0.1:9/never"
raised = 0
for _ in range(2):
    try:
        http_cache.get(dead, timeout=2)
    except Exception:
        raised += 1
results["connection_errors_raise_every_time"] = raised == 2
server.shutdown()

# ---- registry snapshot
reads = {"n": 0}
real_read = checks._read_subkeys


def counting_read(root, path, names):
    reads["n"] += 1
    return real_read(root, path, names)


checks._read_subkeys = counting_read
try:
    checks.invalidate_registry_cache()
    for i in range(25):
        checks.find_uninstall_entry_by_display_name(re.compile(f"no-such-program-{i}"))
        checks.find_dependency_by_display_name(re.compile(f"no-such-dependency-{i}"))
    # 3 uninstall roots (HKLM, HKLM Wow6432Node, HKCU) + 1 dependencies key, each read exactly once
    results["registry_read_once_for_many_lookups"] = reads["n"] == 4

    checks.invalidate_registry_cache()
    checks.find_uninstall_entry_by_display_name(re.compile("x"))
    results["invalidate_forces_reread"] = reads["n"] == 7

    before = reads["n"]
    checks.find_uninstall_command_by_display_name(re.compile("no-such-program"))
    results["uninstall_command_lookup_always_fresh"] = reads["n"] == before + 3
finally:
    checks._read_subkeys = real_read

# same answers as before the snapshot: a real entry is found, with a version
checks.invalidate_registry_cache()
entries = checks._uninstall_entries()
if entries:
    first = entries[0]
    found = checks.find_uninstall_entry_by_display_name(re.compile("^" + re.escape(first["DisplayName"]) + "$"))
    results["lookup_returns_version_or_name"] = found == (first["DisplayVersion"] or first["DisplayName"])
else:
    print("(no Uninstall entries on this machine - skipping the lookup check)")

for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
