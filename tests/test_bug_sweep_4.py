"""
Regression tests for the fourth bug-sweep pass (two independent review
agents, 2026-08-12 — one scoped to core/, one to ui/+tests). Each test locks
in the specific failure scenario found, not just "the fix exists."

Run directly:
    venv\\Scripts\\python.exe tests\\test_bug_sweep_4.py
"""

import ctypes
import dataclasses
import sys
import winreg
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from core import checks, definitions, path_backup, profiles
from core.definitions import InstallContext, InstalledState
from core.paths import get_app_dir
from ui.main_window import STATUS_NOT_INSTALLED, MainWindow
from ui.workers import ResultStatus

_real_information = QMessageBox.information

app = QApplication(sys.argv)
window = MainWindow()
window.show()

results: dict[str, object] = {}
app_dir = get_app_dir()


def after_scan():
    try:
        # --- Bug: .NET SDK uninstall matched by channel only ("8.0.") -
        # multiple SDK patches legitimately coexist side by side, so this
        # could remove whichever patch the registry happened to enumerate
        # first rather than the one actually installed/selected. ---
        fake_registry = ["Microsoft .NET SDK 8.0.403 (x64)", "Microsoft .NET SDK 8.0.404 (x64)"]
        real_find_cmd = checks.find_uninstall_command_by_display_name
        real_run_uninstall = definitions._run_uninstall_command
        real_is_installed = definitions._net_sdk_is_installed

        matches_seen = []

        def fake_find_cmd(pattern):
            matches = [n for n in fake_registry if pattern.search(n)]
            matches_seen.append(matches)
            if not matches:
                return None
            return type("FakeCmd", (), {
                "display_name": matches[0], "quiet_command": None,
                "raw_command": "MsiExec.exe /I{11111111-1111-1111-1111-111111111111}",
            })()

        captured_args = {}
        definitions._net_sdk_is_installed = lambda sd: InstalledState(installed=True, version="8.0.404")
        checks.find_uninstall_command_by_display_name = fake_find_cmd
        definitions._run_uninstall_command = lambda args, name, ctx: captured_args.update(args=args) or True

        sd = definitions._NetSdkDef("8.0")
        definitions._net_sdk_uninstall(sd, InstallContext(temp_dir=app_dir, dry_run=False))

        results["net_sdk_uninstall_pattern_matches_only_the_installed_patch"] = (
            len(matches_seen) == 1 and matches_seen[0] == ["Microsoft .NET SDK 8.0.404 (x64)"]
        )

        definitions._net_sdk_is_installed = real_is_installed
        checks.find_uninstall_command_by_display_name = real_find_cmd
        definitions._run_uninstall_command = real_run_uninstall

        # --- Bug: .NET runtime registry fallback checked for a subkey
        # named after the bare channel (e.g. "...sharedfx\Microsoft.
        # AspNetCore.App\8.0") - InstalledVersions actually records each
        # installed patch as a VALUE NAME under that key, not a subkey, so
        # the fallback could never match anything real. ---
        probe_key = r"Software\RuntimeForgeTest\bugsweep4"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, probe_key) as k:
            winreg.SetValueEx(k, "8.0.403", 0, winreg.REG_SZ, "x")
            winreg.SetValueEx(k, "9.0.100", 0, winreg.REG_SZ, "x")
        try:
            match = checks.reg_value_name_matches("HKCU", probe_key, "8.0.")
            results["reg_value_name_matches_finds_prefixed_value_name"] = match == "8.0.403"
            results["reg_value_name_matches_returns_none_for_unmatched_prefix"] = (
                checks.reg_value_name_matches("HKCU", probe_key, "7.0.") is None
            )
            results["reg_value_name_matches_handles_missing_key"] = (
                checks.reg_value_name_matches("HKCU", probe_key + r"\DoesNotExist", "8.0.") is None
            )
        finally:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, probe_key)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\RuntimeForgeTest")

        # --- Bug: backups_dir()/profiles_dir() let an OSError from mkdir()
        # propagate uncaught, unlike every other directory-creation call in
        # this codebase (ninja/jq install dirs) which fails gracefully. ---
        real_mkdir = Path.mkdir

        def raising_mkdir(self, *a, **k):
            raise OSError("simulated: unwritable location")

        Path.mkdir = raising_mkdir
        try:
            probe_dir = app_dir / "bugsweep4_unwritable_probe"
            d1 = path_backup.backups_dir(probe_dir)
            results["backups_dir_survives_mkdir_failure"] = isinstance(d1, Path)
        except Exception:
            results["backups_dir_survives_mkdir_failure"] = False
        try:
            d2 = profiles.profiles_dir(probe_dir)
            results["profiles_dir_survives_mkdir_failure"] = isinstance(d2, Path)
        except Exception:
            results["profiles_dir_survives_mkdir_failure"] = False
        Path.mkdir = real_mkdir

        # --- Bug: "Relaunch as Administrator" called QApplication.quit()
        # unconditionally, bypassing the exact same "don't destroy a live
        # QThread" guard closeEvent() already has for install/uninstall/
        # scan workers. ---
        real_shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_calls = {"count": 0}

        def fake_shell_execute(*a, **k):
            shell_calls["count"] += 1
            return 42  # > 32 == "accepted" per ShellExecuteW's own convention

        ctypes.windll.shell32.ShellExecuteW = fake_shell_execute
        QMessageBox.information = staticmethod(lambda *a, **k: None)

        class _FakeRunningWorker:
            def isRunning(self):
                return True

        window.install_worker = _FakeRunningWorker()
        window._relaunch_elevated()
        results["relaunch_refuses_while_install_worker_running"] = shell_calls["count"] == 0
        window.install_worker = None

        window.uninstall_worker = _FakeRunningWorker()
        window._relaunch_elevated()
        results["relaunch_refuses_while_uninstall_worker_running"] = shell_calls["count"] == 0
        window.uninstall_worker = None

        real_quit = QApplication.quit
        quit_calls = {"count": 0}
        QApplication.quit = staticmethod(lambda: quit_calls.update(count=quit_calls["count"] + 1))
        window._relaunch_elevated()
        results["relaunch_proceeds_when_nothing_is_running"] = shell_calls["count"] == 1 and quit_calls["count"] == 1
        QApplication.quit = real_quit

        ctypes.windll.shell32.ShellExecuteW = real_shell_execute
        QMessageBox.information = _real_information

        # --- Bug: _on_uninstall_finished read the LIVE Dry Run checkbox
        # instead of the flag the worker actually ran with - toggling Dry
        # Run while a real uninstall is still in flight made a genuinely
        # completed uninstall get reported (and treated) as a no-op. ---
        real_git_component = window.component_by_key["git"]
        window.component_by_key["git"] = dataclasses.replace(
            real_git_component, is_installed=lambda: InstalledState(installed=False, version=None)
        )

        class _FakeUninstallWorker:
            def __init__(self, dry_run):
                self.dry_run = dry_run

        original_dry_run_checked = window.dry_run_checkbox.isChecked()
        window.uninstall_worker = _FakeUninstallWorker(dry_run=False)  # a REAL uninstall was running
        window.dry_run_checkbox.setChecked(True)  # user flips Dry Run on before it reports back
        window._on_uninstall_finished("git", True)

        item = window.tree_items["git"]
        results["uninstall_finished_uses_workers_actual_dry_run_flag"] = item.text(1) == STATUS_NOT_INSTALLED

        window.dry_run_checkbox.setChecked(original_dry_run_checked)
        window.component_by_key["git"] = real_git_component

        # --- Bug: _on_component_finished (install completion) never wrote
        # back to _scan_results - a component installed this run showed no
        # context-menu items and Export Report still called it "Not
        # installed" until the next full Rescan. ---
        window.component_by_key["git"] = dataclasses.replace(
            real_git_component, is_installed=lambda: InstalledState(installed=True, version="2.99.9")
        )
        window._scan_results["git"] = (InstalledState(installed=False, version=None), None)
        window._on_component_finished("git", ResultStatus.INSTALLED, "")
        post_state = window._scan_results["git"][0]
        results["component_finished_updates_scan_results"] = post_state.installed and post_state.version == "2.99.9"
        results["component_finished_updates_version_column"] = window.tree_items["git"].text(2) == "2.99.9"
        window.component_by_key["git"] = real_git_component

        # --- Bug: "Select Missing/Outdated" stayed enabled during a scan,
        # so clicking it mid-scan read a partially-populated _scan_results
        # and could wrongly (de)select already-current components. ---
        window._start_scan()
        results["select_missing_disabled_immediately_after_scan_starts"] = not window.select_missing_btn.isEnabled()
        if window.scan_worker is not None:
            window.scan_worker.wait()
        for _ in range(50):
            app.processEvents()
        results["select_missing_reenabled_after_scan_finishes"] = window.select_missing_btn.isEnabled()

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        QMessageBox.information = _real_information
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\RuntimeForgeTest\bugsweep4")
        except OSError:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\RuntimeForgeTest")
        except OSError:
            pass

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
