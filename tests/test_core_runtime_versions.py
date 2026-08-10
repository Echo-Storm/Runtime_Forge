"""
Regression test for version detection on winget, DirectX, Vulkan, and
WebView2 — all four previously showed a bare "-" for both Installed and
Latest Version, with no way to tell if any of them were current.

winget uses `winget --version` (verified safe on a real machine: returns
immediately, no lingering process — unlike the VS Code incident, winget is
a genuine console CLI tool, not an Electron GUI app). DirectX/Vulkan read
their DLL's own PE VERSIONINFO resource (no process execution at all).
WebView2 reads the Evergreen updater's "pv" registry value. This test
checks tasklist before/after for good measure regardless, since "verified
safe" turned out to be exactly the assumption that broke on VS Code.

Run directly:
    venv\\Scripts\\python.exe tests\\test_core_runtime_versions.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.definitions import build_components
from core.logger import setup_logging
from core.paths import get_app_dir
from core.version_resolvers import version_is_newer

setup_logging(get_app_dir())

results: dict[str, object] = {}


def snapshot_processes() -> str:
    return subprocess.run(["tasklist"], capture_output=True, text=True, timeout=15).stdout


try:
    before = snapshot_processes()

    components = {c.key: c for c in build_components()}

    for key in ["winget", "directx", "vulkan", "webview2"]:
        component = components[key]
        state = component.is_installed()
        if state.installed:
            results[f"{key}_has_a_version"] = bool(state.version)

    time.sleep(2)
    after = snapshot_processes()
    # Loose check: same set of *new* process names shouldn't have appeared.
    # (Not a strict diff since background OS churn is normal; specifically
    # checking the four binaries these checks touch didn't spawn anything
    # that's still around.)
    for exe_name in ["winget.exe", "vulkan-runtime.exe", "MicrosoftEdgeWebview2Setup.exe"]:
        results[f"no_lingering_{exe_name}"] = exe_name.lower() not in after.lower() or exe_name.lower() in before.lower()

    # winget and vulkan have resolve_latest; directx and webview2
    # deliberately don't (no reliable "latest" concept for either).
    winget = components["winget"]
    vulkan = components["vulkan"]
    directx = components["directx"]
    webview2 = components["webview2"]

    results["winget_has_resolve_latest"] = winget.resolve_latest is not None
    results["vulkan_has_resolve_latest"] = vulkan.resolve_latest is not None
    results["directx_has_no_resolve_latest"] = directx.resolve_latest is None
    results["webview2_has_no_resolve_latest"] = webview2.resolve_latest is None

    if winget.is_installed().installed:
        latest = winget.resolve_latest()
        results["winget_latest_comparison_does_not_throw"] = isinstance(
            version_is_newer(latest.version, winget.is_installed().version or ""), bool
        )

    if vulkan.is_installed().installed:
        latest = vulkan.resolve_latest()
        results["vulkan_latest_comparison_does_not_throw"] = isinstance(
            version_is_newer(latest.version, vulkan.is_installed().version or ""), bool
        )

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
