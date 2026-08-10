"""
Automated functional test for the Profiles feature — drives a real
QApplication + MainWindow instance rather than testing logic in isolation,
because the bug this caught (Update targeting the combo's literal selection,
which resets to "Custom" on the very first edit — making "load a profile,
tweak it, click Update" permanently no-op) only shows up when the actual
widget wiring runs end to end.

Not wired into a pytest suite (no such runner in this project yet) — run
directly:
    venv\\Scripts\\python.exe tests\\test_profiles_ui.py
Exits 0 and prints "ALL_OK: True" on success, exits 1 otherwise. Cleans up
its own test profile before exiting either way.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow

TEST_PROFILE_NAME = "QA Test Profile"

# Auto-confirm any modal QMessageBox.question (e.g. the delete-profile
# confirmation) so this script can run unattended instead of hanging on a
# dialog no one is there to click.
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}


def run_test():
    try:
        keys_to_select = ["git", "node", "python_3.13"]
        for key in keys_to_select:
            window.tree_items[key].setCheckState(0, Qt.CheckState.Checked)
        for key, item in window.tree_items.items():
            if key not in keys_to_select:
                item.setCheckState(0, Qt.CheckState.Unchecked)

        results["selection_before_save"] = window._selected_keys() == set(keys_to_select)
        results["combo_is_custom_after_manual_edit"] = window.profile_combo.currentIndex() == 0
        results["update_btn_disabled_no_active_profile"] = not window.profile_update_btn.isEnabled()

        window._write_profile(TEST_PROFILE_NAME)
        results["profile_appears_in_combo"] = window.profile_combo.findText(TEST_PROFILE_NAME) > 0
        results["combo_selected_after_save"] = window._current_profile_name() == TEST_PROFILE_NAME
        results["update_btn_enabled_after_save"] = window.profile_update_btn.isEnabled()
        results["delete_btn_enabled_after_save"] = window.profile_delete_btn.isEnabled()

        # The real-world Update flow: profile is active, then EDIT the
        # selection (resets combo to Custom), then click Update. This is
        # the exact scenario that was broken before the fix.
        window.tree_items["cmake"].setCheckState(0, Qt.CheckState.Checked)
        results["combo_reset_to_custom_after_edit"] = window.profile_combo.currentIndex() == 0
        results["update_btn_still_enabled_after_edit"] = window.profile_update_btn.isEnabled()
        results["delete_btn_disabled_after_edit"] = not window.profile_delete_btn.isEnabled()

        window._on_update_profile()
        updated = [p for p in window._profiles_cache if p.name == TEST_PROFILE_NAME][0]
        results["update_persisted_edited_selection"] = set(updated.component_keys) == set(keys_to_select) | {"cmake"}
        results["combo_shows_profile_again_after_update"] = window._current_profile_name() == TEST_PROFILE_NAME

        window._on_select_all()
        results["combo_reset_after_select_all"] = window.profile_combo.currentIndex() == 0
        idx = window.profile_combo.findText(TEST_PROFILE_NAME)
        window.profile_combo.setCurrentIndex(idx)
        results["profile_reapplied_with_updated_set"] = window._selected_keys() == set(keys_to_select) | {"cmake"}

        window._on_delete_profile()
        results["profile_removed_from_combo"] = window.profile_combo.findText(TEST_PROFILE_NAME) == -1
        results["update_btn_disabled_after_delete_active"] = not window.profile_update_btn.isEnabled()
        results["delete_btn_disabled_on_custom"] = not window.profile_delete_btn.isEnabled()

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        # Belt-and-suspenders cleanup in case an assertion failed before the
        # in-flow delete step ran.
        from core import profiles as profiles_module
        profiles_module.delete_profile(window.app_dir, TEST_PROFILE_NAME)

    for k, v in results.items():
        print(f"{k}: {v}")

    all_ok = "EXCEPTION" not in results and all(results.values())
    print("ALL_OK:", all_ok)
    app.exit(0 if all_ok else 1)


def wait_for_scan():
    # Polls actual scan completion instead of a flat delay - the scan makes
    # live GitHub/Adoptium/nodejs.org calls, so a fixed timer can fire while
    # ScanWorker is still running, letting this test's manual checkbox
    # edits race its in-flight auto-select signal handling.
    if window.scan_worker is not None and window.scan_worker.isRunning():
        QTimer.singleShot(300, wait_for_scan)
    else:
        run_test()


QTimer.singleShot(500, wait_for_scan)
sys.exit(app.exec())
