"""
Regression test for .NET 8/9/10 and Python update detection.

.NET Framework 4.8.1 deliberately has no resolve_latest (serviced via
Windows Update, not a separately versioned redistributable) — checked here
alongside the ones that do, to lock in that it stays None rather than
someone "completing the set" with a guess later.

Python has no external API call at all — "latest" is just what this app's
own pinned _PY_DEFS would actually install, read from the exe's own PE
resource for the installed side rather than the coarse minor version. This
caught a real gap: installed patches were behind the pinned targets on a
real machine (3.13.13 vs 3.13.14, 3.11.9 vs 3.11.15), invisible when only
the coarse "3.13" was ever shown.

Run directly:
    venv\\Scripts\\python.exe tests\\test_net_python_versions.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.definitions import build_components
from core.logger import setup_logging
from core.paths import get_data_dir
from core.version_resolvers import version_is_newer

setup_logging(get_data_dir())

results: dict[str, object] = {}

try:
    components = {c.key: c for c in build_components()}

    net_versioned_keys = [k for k in components if k.startswith("net_") and "Framework" not in k]
    for key in net_versioned_keys:
        c = components[key]
        results[f"{key}_has_resolve_latest"] = c.resolve_latest is not None
        latest = c.resolve_latest()
        results[f"{key}_latest_has_version"] = bool(latest and latest.version)
        state = c.is_installed()
        if state.installed:
            results[f"{key}_comparison_does_not_throw"] = isinstance(
                version_is_newer(latest.version, state.version or ""), bool
            )

    framework = components["net_.NET Framework 4.8.1"]
    # resolve_latest is attached uniformly to every _NET_DEFS entry (same
    # loop, same lambda) — the None-ness lives in what *calling* it
    # returns for the framework case, not in the attribute itself.
    results["net_framework_resolve_latest_call_returns_none"] = framework.resolve_latest() is None

    for key in [k for k in components if k.startswith("python_")]:
        c = components[key]
        results[f"{key}_has_resolve_latest"] = c.resolve_latest is not None
        latest = c.resolve_latest()
        # full_version (e.g. "3.13.14"), never the coarse "3.13" — a
        # regression back to the minor-only string would make every
        # comparison against a real installed patch silently useless.
        results[f"{key}_latest_is_patch_level"] = latest.version.count(".") == 2

        state = c.is_installed()
        if state.installed:
            results[f"{key}_installed_is_patch_level_not_coarse"] = state.version != key.split("_", 1)[1]

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
