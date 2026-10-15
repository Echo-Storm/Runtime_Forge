"""
Regression tests for the third bug-sweep pass (two independent review
agents, 2026-08-10 — one scoped to core/, one to ui/+tests). Each test
locks in the specific failure scenario found, not just "the fix exists."

(refresh_path_env()'s %VAR%-expansion fix has its own dedicated test:
tests/test_path_env_expansion.py — no Qt needed there.)

Run directly:
    venv\\Scripts\\python.exe tests\\test_bug_sweep_3.py
"""

import dataclasses
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

from core import path_backup, profiles
from core.definitions import InstalledState
from core.paths import get_data_dir
from ui.main_window import MainWindow
from ui.workers import InstallWorker, ResultStatus

# Both dialogs are monkeypatched per-test below (not globally at import
# time like test_profiles_ui.py) since this file needs different answers
# from the same dialog across different scenarios (decline the overwrite,
# then confirm it).
_real_question = QMessageBox.question
_real_information = QMessageBox.information
_real_warning = QMessageBox.warning
_real_get_text = QInputDialog.getText

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}
app_dir = get_data_dir()


def after_scan():
    try:
        # --- Bug: Save As silently overwrote an existing (or case-variant)
        # profile with no confirmation ---
        profiles.save_profile(app_dir, profiles.Profile(name="Existing", component_keys=["git"]))
        window._refresh_profile_combo()

        for key, item in window.tree_items.items():
            item.setCheckState(0, Qt.CheckState.Checked if key == "node" else Qt.CheckState.Unchecked)

        QInputDialog.getText = staticmethod(lambda *a, **k: ("existing", True))  # case-variant of "Existing"
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
        window._on_save_profile_as()
        unchanged = profiles.load_profile(profiles.profiles_dir(app_dir) / "Existing.json")
        results["declining_overwrite_leaves_profile_unchanged"] = unchanged is not None and set(unchanged.component_keys) == {"git"}

        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        window._on_save_profile_as()
        # Windows filesystems are case-insensitive - "existing.json" IS
        # "Existing.json" on disk, so confirming here must have overwritten
        # the same physical file the collision check found, not created a
        # second one alongside it.
        remaining_files = [p for p in profiles.profiles_dir(app_dir).glob("*.json") if p.name.lower() == "existing.json"]
        overwritten = profiles.load_profile(remaining_files[0]) if remaining_files else None
        results["confirming_overwrite_replaces_profile_content"] = overwritten is not None and set(overwritten.component_keys) == {"node"}
        results["overwrite_did_not_create_a_second_file"] = len(remaining_files) == 1

        profiles.delete_profile(app_dir, "Existing")
        profiles.delete_profile(app_dir, "existing")
        QInputDialog.getText = _real_get_text
        QMessageBox.question = _real_question

        # --- Bug: PATH-backup combo selection not preserved across refresh ---
        b1 = path_backup.create_backup(app_dir, "sweep3 backup A")
        b2 = path_backup.create_backup(app_dir, "sweep3 backup B")
        window._refresh_path_backup_combo()
        backups_now = path_backup.list_backups(app_dir)
        older_timestamp = backups_now[-1].timestamp  # backups list newest-first; pick the older of the two just made
        for i, b in enumerate(window._path_backups_cache):
            if b.timestamp == older_timestamp:
                window.path_backup_combo.setCurrentIndex(i)
                break
        results["selected_the_older_backup"] = window._selected_path_backup().timestamp == older_timestamp

        path_backup.create_backup(app_dir, "sweep3 unrelated refresh trigger")
        window._refresh_path_backup_combo()  # simulates e.g. an install run finishing elsewhere
        results["selection_preserved_across_unrelated_refresh"] = (
            window._selected_path_backup() is not None and window._selected_path_backup().timestamp == older_timestamp
        )

        # --- Bug: Backup Now didn't select the backup it just created ---
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        before_count = len(path_backup.list_backups(app_dir))
        window._on_backup_path_now()
        after_count = len(path_backup.list_backups(app_dir))
        newest = path_backup.list_backups(app_dir)[0]
        results["backup_now_creates_a_new_backup"] = after_count == before_count + 1
        results["backup_now_selects_the_new_backup"] = (
            window._selected_path_backup() is not None and window._selected_path_backup().timestamp == newest.timestamp
        )
        QMessageBox.information = _real_information

        # --- Bug: restore-failure branch left the combo stale despite a
        # fresh safety backup being written to disk either way ---
        target = window._selected_path_backup()
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        real_restore_backup = path_backup.restore_backup
        path_backup.restore_backup = lambda backup: False  # force the failure branch
        count_before_failed_restore = len(path_backup.list_backups(app_dir))
        window._on_restore_path_backup()
        count_after_failed_restore = len(path_backup.list_backups(app_dir))
        results["failed_restore_still_creates_safety_backup"] = count_after_failed_restore == count_before_failed_restore + 1
        results["failed_restore_still_refreshes_combo"] = window.path_backup_combo.count() == count_after_failed_restore
        path_backup.restore_backup = real_restore_backup
        QMessageBox.question = _real_question
        QMessageBox.warning = _real_warning

        # Clean up every backup this test created.
        for f in path_backup.backups_dir(app_dir).glob("path_backup_*.json"):
            f.unlink(missing_ok=True)

        # --- Bug: an update-check failure looked identical to "already
        # current" in both the log and the emitted result ---
        finished_events = []

        def collect(key, status, warning):
            finished_events.append((key, status, warning))

        def raise_on_resolve():
            raise RuntimeError("simulated network failure")

        real_component = window.component_by_key["cmake"]
        flaky_component = dataclasses.replace(
            real_component,
            is_installed=lambda: InstalledState(installed=True, version="1.0.0"),
            resolve_latest=raise_on_resolve,
        )
        worker = InstallWorker([flaky_component], {"cmake"}, dry_run=False)
        worker.component_finished.connect(collect)
        worker.run()
        results["update_check_failure_reported_as_skipped_not_crashed"] = (
            len(finished_events) == 1 and finished_events[0][1] == ResultStatus.SKIPPED
        )
        results["update_check_failure_warning_distinguishes_from_confirmed_current"] = (
            len(finished_events) == 1 and "update check failed" in finished_events[0][2]
        )

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        QInputDialog.getText = _real_get_text
        QMessageBox.question = _real_question
        QMessageBox.information = _real_information
        QMessageBox.warning = _real_warning
        profiles.delete_profile(app_dir, "Existing")
        profiles.delete_profile(app_dir, "existing")
        for f in path_backup.backups_dir(app_dir).glob("path_backup_*.json"):
            f.unlink(missing_ok=True)

    for k, v in results.items():
        print(f"{k}: {v}")

    all_ok = "EXCEPTION" not in results and all(results.values())
    print("ALL_OK:", all_ok)
    app.exit(0 if all_ok else 1)


def wait_for_scan():
    if window.scan_worker is not None and window.scan_worker.isRunning():
        QTimer.singleShot(300, wait_for_scan)
    else:
        after_scan()


QTimer.singleShot(1000, wait_for_scan)
sys.exit(app.exec())
