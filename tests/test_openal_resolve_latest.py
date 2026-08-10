"""
Regression test for a real mistake: the first version of
_openal_resolve_latest() just echoed back a hand-pinned "1.25.1" as both
the install target AND "latest" — comparing a pinned value against itself
can never detect a real update. Confirmed live (2026-08-10): the real
latest release was 1.25.2, one patch ahead of what was pinned. Fixed to
use the same GitHub-releases pattern as git-for-windows/CMake/PowerShell —
a real external source, not a self-referential echo.

This test locks in the structural property that would have caught the
original mistake: resolve_latest() must point at a real GitHub release
URL, not the old static openal-soft.org pinned zip URL.

Run directly:
    venv\\Scripts\\python.exe tests\\test_openal_resolve_latest.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.definitions import build_components
from core.logger import setup_logging
from core.paths import get_app_dir
from core.version_resolvers import version_is_newer

setup_logging(get_app_dir())

results: dict[str, object] = {}

try:
    components = {c.key: c for c in build_components()}
    openal = components["openal"]

    results["has_resolve_latest"] = openal.resolve_latest is not None
    latest = openal.resolve_latest()

    results["resolves_to_a_real_github_release_url"] = latest.url.startswith(
        "https://github.com/kcat/openal-soft/releases/download/"
    )
    # The specific bug: resolve_latest() must not be hardcoded to whatever
    # string install() happens to also use — calling it twice must agree
    # (same underlying source), and it must NOT match the old static
    # openal-soft.org URL that used to be duplicated in both places.
    latest_again = openal.resolve_latest()
    results["resolve_latest_is_consistent_across_calls"] = latest.url == latest_again.url
    results["does_not_use_old_static_openal_soft_org_url"] = "openal-soft.org" not in latest.url

    state = openal.is_installed()
    if state.installed and state.version:
        # Not asserting an update IS available (this machine may already be
        # current by the time this runs) — just that the comparison
        # machinery works and doesn't throw.
        results["version_comparison_does_not_throw"] = isinstance(
            version_is_newer(latest.version, state.version), bool
        )

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
