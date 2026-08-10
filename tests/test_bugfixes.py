"""
Regression tests for specific bugs an independent review pass caught before
they shipped (see git log for the fix commits). Each test is named after
the failure scenario it locks in, not the fix, so it stays meaningful if
the implementation changes later.

Run directly:
    venv\\Scripts\\python.exe tests\\test_bugfixes.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from core.logger import get_logger
from core.profiles import safe_filename
from ui.main_window import MainWindow
from ui.workers import InstallWorker

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}


def after_scan():
    try:
        # --- Rescan must not silently re-check a manually unchecked item ---
        # Must be a component the scan actually auto-checked (missing, or
        # has an update) - not just the first dict-order key. That was
        # "winget", which is already-installed-and-current on virtually
        # every real dev machine, so unchecking-then-reasserting-unchecked
        # passed trivially without ever exercising the guard this test
        # claims to verify (it would pass even with the guard deleted).
        auto_checked = [key for key, item in window.tree_items.items() if item.checkState(0) == Qt.CheckState.Checked]
        if auto_checked:
            a_key = auto_checked[0]
        else:
            # Every component happened to already be installed/current on
            # this machine - force one to Checked so the guard is still
            # genuinely exercised instead of silently no-op'ing.
            a_key = next(iter(window.tree_items))
            window.tree_items[a_key].setCheckState(0, Qt.CheckState.Checked)
        window.tree_items[a_key].setCheckState(0, Qt.CheckState.Unchecked)
        window._on_scan_finished()  # simulate a second scan's completion without a real rescan
        for key, (state, latest) in window._scan_results.items():
            window._on_component_scanned(key, state, latest)  # re-deliver the same scan results, as a real Rescan would
        results["rescan_does_not_reselect_manually_unchecked_item"] = (
            window.tree_items[a_key].checkState(0) == Qt.CheckState.Unchecked
        )

        # --- safe_filename blocks reserved device names ---
        results["safe_filename_blocks_reserved_names"] = (
            safe_filename("CON") != "CON" and safe_filename("con") != "con"
        )
        results["safe_filename_strips_trailing_dot_space"] = (
            safe_filename("Trailing.") == "Trailing" and safe_filename("Trailing ") == "Trailing"
        )

        # --- Logger listener leak: two InstallWorker runs must not double-emit ---
        log = get_logger()
        listener_count_before = len(log._listeners)
        worker1 = InstallWorker(window.components, set(), dry_run=True)
        worker1.run()
        worker2 = InstallWorker(window.components, set(), dry_run=True)
        worker2.run()
        results["install_worker_does_not_leak_log_listeners"] = len(log._listeners) == listener_count_before

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
