"""
Tests for the published version catalog (core/published.py, data/versions.json,
tools/update_versions.py) and how the resolvers use it.

Offline: the catalog fetch and GitHub's API are faked.

Run directly:
    venv\\Scripts\\python.exe tests\\test_published.py
"""

import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

os.environ.pop("RUNTIME_FORGE_NO_CATALOG", None)   # these tests are about the catalog
os.environ.pop("GITHUB_TOKEN", None)
os.environ.pop("GH_TOKEN", None)

from core import catalog, definitions, http_cache, published, version_resolvers
from core.logger import setup_logging
from core.version_resolvers import LatestInfo

tmp = Path(tempfile.mkdtemp(prefix="rf_published_"))
setup_logging(tmp)
results = {}


class _Resp:
    def __init__(self, payload=None, ok=True):
        self._payload, self.ok = payload, ok

    def raise_for_status(self):
        if not self.ok:
            raise OSError("404")

    def json(self):
        return self._payload


def doc(entries=None, generated=None, schema=1):
    return {
        "schema": schema,
        "generated": (generated or datetime.date.today()).isoformat(),
        "entries": entries if entries is not None else {"o/r": GOOD},
    }


GOOD = {"version": "1.2.3", "url": "https://github.com/o/r/releases/download/v1.2.3/tool-win.zip",
        "filename": "tool-win.zip", "sha256": "AB" * 32}
PATTERN = re.compile(r"^tool-win\.zip$")
real_get = http_cache.get


def serve(payload, ok=True):
    http_cache.clear()
    http_cache.get = lambda *a, **k: _Resp(payload, ok)


def serve_error():
    http_cache.clear()

    def boom(*a, **k):
        raise OSError("offline")
    http_cache.get = boom


try:
    # ---- lookup
    serve(doc())
    got = published.lookup("o/r", PATTERN)
    results["lookup_returns_the_entry"] = got == LatestInfo("1.2.3", GOOD["url"], "tool-win.zip", "ab" * 32)
    results["sha256_is_normalised_to_lowercase"] = got.sha256 == "ab" * 32
    results["unknown_repo_is_none"] = published.lookup("x/y", PATTERN) is None
    results["filename_must_match_the_components_pattern"] = published.lookup("o/r", re.compile(r"^other\.zip$")) is None

    serve(doc(generated=datetime.date.today() - datetime.timedelta(days=published.MAX_AGE_DAYS + 1)))
    results["stale_catalog_is_ignored"] = published.lookup("o/r", PATTERN) is None
    serve(doc(generated=datetime.date.today() - datetime.timedelta(days=published.MAX_AGE_DAYS - 1)))
    results["recent_enough_catalog_is_used"] = published.lookup("o/r", PATTERN) is not None
    serve(doc(schema=2))
    results["unknown_schema_is_ignored"] = published.lookup("o/r", PATTERN) is None
    serve({"nonsense": True})
    results["malformed_document_is_ignored"] = published.lookup("o/r", PATTERN) is None
    serve(None, ok=False)
    results["http_error_means_no_catalog"] = published.lookup("o/r", PATTERN) is None
    serve_error()
    results["offline_means_no_catalog"] = published.lookup("o/r", PATTERN) is None

    for label, bad in {
        "non_github_url": dict(GOOD, url="https://evil.example/tool-win.zip"),
        "http_url": dict(GOOD, url="http://github.com/o/r/releases/download/v1/tool-win.zip"),
        "bad_sha256": dict(GOOD, sha256="nothex"),
        "missing_version": {k: v for k, v in GOOD.items() if k != "version"},
        "empty_filename": dict(GOOD, filename=""),
    }.items():
        serve(doc({"o/r": bad}))
        results[f"bad_entry_is_ignored_{label}"] = published.lookup("o/r", PATTERN) is None

    serve(doc({"o/r": dict(GOOD, sha256=None)}))
    results["an_entry_without_a_hash_is_allowed_but_has_none"] = published.lookup("o/r", PATTERN).sha256 is None

    # ---- when the catalog must stay out of the way
    serve(doc())
    os.environ["GITHUB_TOKEN"] = "x"
    results["a_github_token_means_live_lookups"] = published.lookup("o/r", PATTERN) is None
    del os.environ["GITHUB_TOKEN"]
    os.environ["RUNTIME_FORGE_NO_CATALOG"] = "1"
    results["no_catalog_env_switch"] = published.lookup("o/r", PATTERN) is None
    del os.environ["RUNTIME_FORGE_NO_CATALOG"]
    published.disable()
    results["disable_switch"] = published.lookup("o/r", PATTERN) is None
    published.enable()
    published.set_strict(True)
    results["strict_mode_skips_it"] = published.lookup("o/r", PATTERN) is None
    published.set_strict(False)
    results["back_to_normal_after_toggles"] = published.lookup("o/r", PATTERN) is not None

    # ---- resolvers take the catalog first and never touch the API when it answers
    api_calls = []
    entry = {"version": "9.9.9", "url": "https://github.com/git-for-windows/git/releases/download/v9.9.9/Git-9.9.9-64-bit.exe",
             "filename": "Git-9.9.9-64-bit.exe", "sha256": "cd" * 32}

    def catalog_only(url, *a, **k):
        if url == published.CATALOG_URL:
            return _Resp(doc({"git-for-windows/git": entry, "microsoft/terminal": dict(
                entry, filename="Microsoft.WindowsTerminal_9.9.9_8wekyb3d8bbwe.msixbundle",
                url="https://github.com/microsoft/terminal/releases/download/v9.9.9/Microsoft.WindowsTerminal_9.9.9_8wekyb3d8bbwe.msixbundle"),
                "adoptium/temurin21-binaries": dict(
                    entry, version="21.0.99+1", filename="OpenJDK21U-jdk_x64_windows_hotspot_21.0.99_1.msi",
                    url="https://github.com/adoptium/temurin21-binaries/releases/download/x/OpenJDK21U-jdk_x64_windows_hotspot_21.0.99_1.msi"),
                "llvm/llvm-project": dict(entry, version="22.9.9", filename="LLVM-22.9.9-win64.exe",
                                          url="https://github.com/llvm/llvm-project/releases/download/llvmorg-22.9.9/LLVM-22.9.9-win64.exe"),
                "jqlang/jq": dict(entry, version="1.9.9", filename="jq.exe",
                                  url="https://github.com/jqlang/jq/releases/download/jq-1.9.9/jq-windows-amd64.exe")}))
        api_calls.append(url)
        raise AssertionError(f"unexpected live request: {url}")

    http_cache.clear()
    http_cache.get = catalog_only
    git = definitions._git_resolve_latest()
    results["git_resolves_from_the_catalog"] = git.version == "9.9.9" and git.filename == "Git-9.9.9-64-bit.exe" and git.sha256 == "cd" * 32
    results["terminal_resolves_from_the_catalog"] = catalog._terminal_resolve().version == "9.9.9"
    results["temurin_resolves_from_the_catalog"] = version_resolvers.get_latest_temurin(21, "21.0.1").version == "21.0.99+1"
    results["llvm_resolves_from_the_catalog"] = definitions._llvm_resolve_latest().version == "22.9.9"
    jq = definitions._jq_resolve_latest()
    results["jq_resolves_from_the_catalog_and_keeps_its_cache_filename"] = jq.version == "1.9.9" and jq.filename == "jq.exe"
    results["no_api_calls_when_the_catalog_answers"] = api_calls == []

    # ---- without the catalog the live path (and its pinned fallback) still works
    def api_only(url, *a, **k):
        if url == published.CATALOG_URL:
            return _Resp(None, ok=False)
        if "/releases/latest" in url:
            return _Resp({"tag_name": "v1.0.0", "assets": [
                {"name": "Git-1.0.0-64-bit.exe", "browser_download_url": "https://github.com/x/Git-1.0.0-64-bit.exe", "digest": "sha256:" + "ef" * 32}]})
        raise OSError("offline")

    http_cache.clear()
    http_cache.get = api_only
    live = definitions._git_resolve_latest()
    results["live_api_is_the_fallback"] = live.version == "1.0.0" and live.sha256 == "ef" * 32

    def everything_down(url, *a, **k):
        raise OSError("offline")

    http_cache.clear()
    http_cache.get = everything_down
    pinned = definitions._git_resolve_latest()
    results["pinned_fallback_when_nothing_answers"] = pinned.version == definitions._GIT_FALLBACK_VERSION

    published.set_strict(True)
    http_cache.clear()
    for name, call in {
        "git": definitions._git_resolve_latest, "terminal": catalog._terminal_resolve,
        "llvm": definitions._llvm_resolve_latest, "jq": definitions._jq_resolve_latest,
        "temurin": lambda: version_resolvers.get_latest_temurin(21, "21.0.1"),
    }.items():
        try:
            call()
            results[f"strict_mode_refuses_a_pinned_fallback_{name}"] = False
        except Exception:
            results[f"strict_mode_refuses_a_pinned_fallback_{name}"] = True
    published.set_strict(False)
finally:
    http_cache.get = real_get
    published.enable()
    published.set_strict(False)

# ---- the generator
import update_versions

class _C:
    def __init__(self, info=None, boom=False):
        self.info, self.boom = info, boom

    @property
    def resolve_latest(self):
        def resolve():
            if self.boom:
                raise OSError("lookup failed")
            return self.info
        return resolve


good = LatestInfo("1.0", "https://github.com/a/b/releases/download/1.0/b.zip", "b.zip", "AA" * 32)
entries, problems = update_versions.build_entries(
    {"one": _C(good), "two": _C(boom=True), "three": _C(LatestInfo("1", "https://elsewhere/x.zip", "x.zip", "aa" * 32)),
     "four": _C(LatestInfo("1", "https://github.com/a/b/x.zip", "x.zip", None))},
    {"one": "a/b", "two": "c/d", "three": "e/f", "four": "g/h", "five": "i/j"}, log=lambda *_: None)
results["generator_publishes_complete_entries"] = entries == {"a/b": {"version": "1.0", "url": good.url, "filename": "b.zip", "sha256": "aa" * 32}}
results["generator_skips_and_reports_failures"] = len(problems) == 4 and any("lookup failed" in p for p in problems)
results["generator_refuses_non_github_urls_and_missing_hashes"] = "e/f" not in entries and "g/h" not in entries

# ---- the committed catalog is well-formed and covers every component
committed = json.loads((PROJECT_ROOT / "data" / "versions.json").read_text(encoding="utf-8"))
results["committed_catalog_has_the_right_schema"] = committed["schema"] == published.SCHEMA and bool(committed["generated"])
results["committed_catalog_covers_every_repo"] = set(committed["entries"]) == set(published.REPOS.values())
results["committed_entries_all_pass_the_apps_own_validation"] = all(
    e["url"].startswith("https://github.com/") and re.fullmatch(r"[0-9a-f]{64}", e["sha256"]) and e["version"] and e["filename"]
    for e in committed["entries"].values()
)
workflow = (PROJECT_ROOT / ".github" / "workflows" / "update-versions.yml").read_text(encoding="utf-8")
results["workflow_runs_the_generator_daily"] = "tools/update_versions.py" in workflow and "cron:" in workflow and "windows-latest" in workflow

for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
