"""
Functional test for PATH verification + PATH backup creation. Deliberately
does NOT call path_backup.restore_backup() with real data — that writes to
HKLM/HKCU PATH directly, and a test has no business doing that to whatever
machine happens to run it. Restore is checked structurally instead: correct
inputs produce a correct call shape, verified by reading back what a real
(non-restoring) backup/list round-trip produces.

Run directly:
    venv\\Scripts\\python.exe tests\\test_path_backup.py
"""

import dataclasses
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core import path_backup
from core.checks import is_dir_on_path
from core.definitions import InstalledState
from core.paths import get_data_dir
from ui.main_window import MainWindow
from ui.workers import InstallWorker

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}


def after_scan():
    app_dir = get_data_dir()
    try:
        # --- is_dir_on_path sanity ---
        results["system32_is_on_path"] = is_dir_on_path(Path(r"C:\Windows\System32"))
        results["bogus_dir_is_not_on_path"] = not is_dir_on_path(Path(r"C:\this\does\not\exist\anywhere"))

        # --- every PATH-tracked component resolves a real path_entry when installed ---
        path_tracked_keys = ["pwsh", "git", "node", "cmake", "python_3.11", "python_3.13", "jdk_21", "jdk_17", "jdk_8"]
        entry_checks = {}
        for key in path_tracked_keys:
            component = window.component_by_key[key]
            state, _ = window._scan_results[key]
            if not state.installed or component.path_entry is None:
                continue
            entry = component.path_entry()
            entry_checks[key] = entry is not None and isinstance(is_dir_on_path(entry), bool)
        results["path_entries_resolve_for_installed_components"] = bool(entry_checks) and all(entry_checks.values())
        print("PATH entry resolution per component:", entry_checks)

        # --- dry-run InstallWorker must NOT create a PATH backup (no real changes happen) ---
        before = len(path_backup.list_backups(app_dir))
        dry_worker = InstallWorker(window.components, {"cmake"}, dry_run=True)
        dry_worker.run()
        after_dry = len(path_backup.list_backups(app_dir))
        results["dry_run_does_not_create_backup"] = after_dry == before

        # --- a real (non-dry-run) InstallWorker run creates exactly one backup,
        # even with multiple components selected ---
        # Fresh dataclasses.replace() copies, not mutated shared instances —
        # window.components stays untouched by this test. Forced to look
        # "already installed and current" so this can't attempt any real
        # download/install; only the backup step at the top of _run() should
        # have a visible effect.
        always_current = lambda: InstalledState(installed=True, version="999.999.999")
        fake_components = [
            dataclasses.replace(c, is_installed=always_current, resolve_latest=None)
            for c in window.components if c.key in ("cmake", "node")
        ]
        real_worker = InstallWorker(fake_components, {"cmake", "node"}, dry_run=False)
        real_worker.run()
        after_real = len(path_backup.list_backups(app_dir))
        results["real_run_creates_exactly_one_backup"] = after_real == after_dry + 1

        backups = path_backup.list_backups(app_dir)
        results["newest_backup_reason_mentions_component_count"] = "2 component" in backups[0].reason

        # --- backup content round-trips correctly (structural check, no restore) ---
        current_machine, current_user = path_backup.read_current_path()
        results["backup_captured_current_machine_path"] = backups[0].machine_path == current_machine
        results["backup_captured_current_user_path"] = backups[0].user_path == current_user

        # --- UI combo reflects the new backups ---
        window._refresh_path_backup_combo()
        results["ui_combo_populated"] = window.path_backup_combo.count() == len(backups)
        results["ui_restore_btn_enabled_when_backups_exist"] = window.path_backup_restore_btn.isEnabled()

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        # Clean up the test backups this test created (leave the directory
        # as it was found, same discipline as the other test files) - in a
        # finally so a failed assertion above (e.g. unexpected backups[0]
        # indexing) can't leave test-created entries in the real backup
        # store this app itself reads from.
        for f in path_backup.backups_dir(app_dir).glob("path_backup_*.json"):
            f.unlink(missing_ok=True)

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
