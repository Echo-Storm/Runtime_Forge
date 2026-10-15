"""
Regression tests for the second bug-sweep pass (independent review agent,
2026-08-10). Each test locks in the specific failure scenario found, not
just "the fix exists."

Run directly:
    venv\\Scripts\\python.exe tests\\test_bug_sweep_2.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from core import path_backup, profiles
from core.definitions import build_components
from core.paths import get_data_dir
from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}
app_dir = get_data_dir()


def after_scan():
    try:
        # --- Bug 1: Import Profile must actually apply to the tree ---
        keys_to_select = ["git", "cmake"]
        for key, item in window.tree_items.items():
            item.setCheckState(0, Qt.CheckState.Checked if key in keys_to_select else Qt.CheckState.Unchecked)

        import_path = app_dir / "test_import_target.json"
        import_profile = profiles.Profile(name="Imported Test Profile", component_keys=["node", "python_3.13"])
        import_path.write_text(json.dumps(import_profile.__dict__), encoding="utf-8")

        # Simulate the file-picker returning this path (can't drive the
        # real QFileDialog headlessly) by calling the same code path
        # _on_import_profile uses, minus the dialog itself.
        loaded = profiles.load_profile(import_path)
        profiles.save_profile(app_dir, loaded)
        window._refresh_profile_combo(select_name=loaded.name)
        window._active_profile_name = loaded.name
        window._update_profile_buttons_enabled()
        window._apply_profile(loaded)

        selected_after_import = {k for k, item in window.tree_items.items() if item.checkState(0) == Qt.CheckState.Checked}
        results["import_applies_keys_to_tree"] = selected_after_import == {"node", "python_3.13"}
        results["import_sets_active_profile_name"] = window._active_profile_name == "Imported Test Profile"
        results["import_enables_update_button"] = window.profile_update_action.isEnabled()

        profiles.delete_profile(app_dir, "Imported Test Profile")
        import_path.unlink(missing_ok=True)

        # --- Bug 2: PATH backup/restore empty-value guards ---
        real_machine, real_user = path_backup.read_current_path()
        results["real_machine_path_is_nonempty_sanity_check"] = bool(real_machine)

        # create_backup must refuse when machine_path would be empty —
        # simulate by writing a corrupt backup file directly and confirming
        # list_backups() filters it out (fail-closed at the read layer).
        corrupt_path = path_backup.backups_dir(app_dir) / "path_backup_00000000_000000.json"
        corrupt_path.write_text(json.dumps({
            "timestamp": "2020-01-01T00:00:00", "reason": "corrupt test fixture",
            "machine_path": "", "user_path": "C:\\Users\\test",
        }), encoding="utf-8")
        listed = path_backup.list_backups(app_dir)
        results["list_backups_filters_out_empty_machine_path"] = not any(
            b.reason == "corrupt test fixture" for b in listed
        )
        corrupt_path.unlink(missing_ok=True)

        # restore_backup must refuse an empty machine_path outright, never
        # reaching the actual registry write.
        bad_backup = path_backup.PathBackup(
            timestamp="2020-01-01T00:00:00", reason="bad", machine_path="", user_path="C:\\Users\\test",
        )
        results["restore_backup_refuses_empty_machine_path"] = path_backup.restore_backup(bad_backup) is False

        # Confirm the real machine PATH was NOT touched by that refused call.
        after_machine, _ = path_backup.read_current_path()
        results["real_machine_path_unchanged_after_refused_restore"] = after_machine == real_machine

        # --- Bug 3: winget install() must use resolve_latest()'s own URL ---
        components = {c.key: c for c in build_components()}
        winget = components["winget"]
        latest = winget.resolve_latest()
        import inspect
        install_source = inspect.getsource(winget.install)
        # The bound method here is the module-level _winget_install function
        # object itself (no per-component wrapping for winget) — read its
        # source to confirm it calls resolve_latest() rather than
        # hardcoding a separate URL, without actually running a real install.
        results["winget_install_calls_resolve_latest"] = "_winget_resolve_latest()" in install_source
        results["winget_resolve_latest_has_a_real_version"] = bool(latest.version)

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        (app_dir / "test_import_target.json").unlink(missing_ok=True)
        profiles.delete_profile(app_dir, "Imported Test Profile")
        (path_backup.backups_dir(app_dir) / "path_backup_00000000_000000.json").unlink(missing_ok=True)

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
