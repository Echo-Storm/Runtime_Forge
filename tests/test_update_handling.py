"""
Automated functional test for update handling: InstallWorker used to skip
ANY already-installed component unconditionally, so the UI's "Installed
(vX) -> vY available" indicator was cosmetic-only — checking that box and
clicking Install did nothing but log a skip. This drives a real
ScanWorker + InstallWorker against whatever's actually on the machine to
prove the fix: components with a genuine available update get installed
(dry run — this test never touches the real system), components that are
already current still get skipped.

Needs at least one Dev Tools component (git/node/cmake/pwsh) to actually
have an update available on the machine it runs on to meaningfully cover
the "don't skip" path — if every single one is already current, that
assertion is skipped rather than failed, since it isn't this test's job to
manufacture a stale install.

Run directly:
    venv\\Scripts\\python.exe tests\\test_update_handling.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core.version_resolvers import version_is_newer
from ui.main_window import MainWindow
from ui.workers import InstallWorker, ResultStatus

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}
VERSIONED_KEYS = ["git", "node", "cmake", "pwsh", "jdk_21", "jdk_17", "jdk_8"]


def after_scan():
    try:
        # Sanity: every versioned component's has_update flag must agree
        # with a fresh independent call to version_is_newer — catches any
        # future drift between the cached scan result and the real logic.
        for key in VERSIONED_KEYS:
            state, latest = window._scan_results[key]
            expected = bool(state.installed and latest and version_is_newer(latest.version, state.version or ""))
            results[f"has_update_matches_{key}"] = window._has_update(state, latest) == expected

        outdated = [k for k in VERSIONED_KEYS if window._has_update(*window._scan_results[k])]
        current = [k for k in VERSIONED_KEYS if window._scan_results[k][0].installed and k not in outdated]

        results["outdated_components_are_checked"] = all(
            window.tree_items[k].checkState(0).value != 0 for k in outdated
        ) if outdated else True

        if not outdated:
            print("NOTE: nothing on this machine has an update available right now — skipping the don't-skip assertion")
            results["install_worker_does_not_skip_outdated"] = True  # nothing to prove, don't fail
        else:
            target = outdated[0]
            worker = InstallWorker(window.components, {target}, dry_run=True)
            outcomes = {}
            worker.component_finished.connect(lambda key, status: outcomes.__setitem__(key, status))
            worker.run()  # synchronous call, not .start() — fine for a dry run in a test
            results["install_worker_does_not_skip_outdated"] = outcomes.get(target) == ResultStatus.INSTALLED

        if current:
            target = current[0]
            worker2 = InstallWorker(window.components, {target}, dry_run=True)
            outcomes2 = {}
            worker2.component_finished.connect(lambda key, status: outcomes2.__setitem__(key, status))
            worker2.run()
            results["install_worker_still_skips_current"] = outcomes2.get(target) == ResultStatus.SKIPPED
        else:
            results["install_worker_still_skips_current"] = True

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    for k, v in results.items():
        print(f"{k}: {v}")

    all_ok = "EXCEPTION" not in results and all(results.values())
    print("ALL_OK:", all_ok)
    app.exit(0 if all_ok else 1)


def wait_for_scan():
    if window.scan_worker is not None and window.scan_worker.isRunning():
        QTimer.singleShot(500, wait_for_scan)
    else:
        after_scan()


QTimer.singleShot(1000, wait_for_scan)
sys.exit(app.exec())
