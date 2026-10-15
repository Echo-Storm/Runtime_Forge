"""
Regression test for VS Code version detection.

Before this fix, _vscode_is_installed() never captured a version at all
(no update detection was even possible for VS Code), and the natural fix
— running `Code.exe --version` — turned out to have a real side effect:
confirmed on a real machine that the raw exe (unlike the `code` CLI shim)
does a full Electron app bootstrap before handling that flag, visibly
launching the app instead of a fast print-and-exit. The actual fix reads
the version from Code.exe's own PE VERSIONINFO resource instead — this
test's main job is confirming that stays true, since running the app
again as a "regression" would be a worse outcome than the bug itself.

Run directly:
    venv\\Scripts\\python.exe tests\\test_vscode_version.py
"""

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.checks import is_dir_on_path
from core.definitions import build_components
from core.logger import setup_logging
from core.paths import get_data_dir
from core.version_resolvers import version_is_newer

setup_logging(get_data_dir())

results: dict[str, object] = {}


def code_exe_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Code.exe"],
        capture_output=True, text=True, timeout=15,
    ).stdout
    return "Code.exe" in out


try:
    components = {c.key: c for c in build_components()}
    vscode = components["vscode"]

    was_running_before = code_exe_running()

    state = vscode.is_installed()
    results["is_installed_returns_a_version"] = bool(state.version)

    # The actual point of this test: confirm the version check itself
    # never launches the app. Small delay since a launch, if one happened,
    # takes a moment to show up in tasklist.
    time.sleep(2)
    results["is_installed_does_not_launch_vscode"] = code_exe_running() == was_running_before

    if state.installed and vscode.resolve_latest:
        latest = vscode.resolve_latest()
        results["resolve_latest_returns_a_version"] = bool(latest and latest.version)
        results["resolve_latest_returns_a_url"] = bool(latest and latest.url.startswith("https://"))
        # Not asserting an update IS available (this machine may already be
        # current by the time this runs) — just that the comparison doesn't
        # throw and returns a bool either way.
        results["version_comparison_does_not_throw"] = isinstance(
            version_is_newer(latest.version, state.version), bool
        )

    if state.installed and vscode.path_entry:
        entry = vscode.path_entry()
        results["path_entry_resolves_to_bin_dir"] = entry is not None and entry.name == "bin"
        results["path_entry_is_a_real_directory"] = entry is not None and entry.is_dir()
        results["is_dir_on_path_does_not_throw"] = isinstance(is_dir_on_path(entry), bool) if entry else False

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
