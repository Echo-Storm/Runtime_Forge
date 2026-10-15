"""
Tests for "make the newest Python the default" (core/python_default.py), the
install flags that keep older Pythons off PATH, and the menu action.

Offline and side-effect free: the registry and PATH writes are faked.

Run directly:
    venv\\Scripts\\python.exe tests\\test_python_default.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication, QMessageBox

from core import definitions, path_backup, python_default as pd
from core.definitions import InstallContext, build_components
from core.logger import setup_logging
from core.python_default import PythonInstall

tmp = Path(tempfile.mkdtemp(prefix="rf_pydefault_"))
setup_logging(tmp)
results = {}


def py(version, install_dir, all_users=True):
    major, minor = (int(n) for n in version.split("."))
    return PythonInstall(version, (major, minor), Path(install_dir), Path(install_dir) / "python.exe", all_users)


P314 = py("3.14", r"E:\Python314", all_users=False)
P313 = py("3.13", r"C:\Program Files\Python313")
P311 = py("3.11", r"C:\Program Files\Python311")
APPDATA = r"C:\Users\Me\AppData\Roaming"

# ---- the plan (the author's real PATH shape: 3.13 first, duplicated, plus user-site entries)
PF = "C:\\Program Files"
machine = ";".join([
    PF + "\\Python313\\Scripts\\", PF + "\\Python313\\",
    r"C:\Windows\system32", r"C:\msys64\mingw64\bin",
    PF + "\\Python313", PF + "\\Python313\\Scripts",
    r"C:\Users\Me\AppData\Roaming\Python\Python313\Scripts", r"C:\Users\Me\AppData\Roaming\Python\Python313",
    PF + "\\Python311\\Scripts\\", PF + "\\Python311\\",
    PF + "\\Git\\cmd",
])
user = r"C:\Users\Me\AppData\Local\Microsoft\WindowsApps;E:\Python314\Scripts\;E:\Python314\;C:\Users\Me\bin"
plan = pd.plan_make_default(machine, user, [P314, P313, P311], appdata=APPDATA)

new_machine = plan.new_machine.split(";")
results["newest_is_chosen"] = plan.latest.version == "3.14"
results["newest_goes_first_on_the_machine_path"] = new_machine[:2] == ["E:\\Python314\\", "E:\\Python314\\Scripts\\"]
results["older_python_folders_are_removed_in_every_spelling"] = not any(
    "python313" in e.lower() or "python311" in e.lower() for e in new_machine
)
results["unrelated_entries_survive_in_order"] = new_machine[2:] == [
    r"C:\Windows\system32", r"C:\msys64\mingw64\bin", r"C:\Program Files\Git\cmd"]
results["newest_removed_from_user_path_so_it_isnt_listed_twice"] = "Python314" not in plan.new_user
results["user_path_otherwise_untouched"] = plan.new_user.split(";") == [
    r"C:\Users\Me\AppData\Local\Microsoft\WindowsApps", r"C:\Users\Me\bin"]
results["plan_reports_what_it_removes"] = len([r for r in plan.removed if r[0] == "machine"]) == 8
results["plan_reports_what_it_adds"] = [e for _, e in plan.added] == ["E:\\Python314\\", "E:\\Python314\\Scripts\\"]
results["plan_is_marked_changed"] = plan.changed

# ---- idempotent
again = pd.plan_make_default(plan.new_machine, plan.new_user, [P314, P313, P311], appdata=APPDATA)
results["second_run_changes_nothing"] = not again.changed and not again.removed and not again.added

# ---- a single Python still gets moved to the front; an already-first one is left alone
solo = pd.plan_make_default(r"C:\a;C:\Program Files\Python313;C:\b", "", [P313], appdata=APPDATA)
results["lone_python_is_moved_to_the_front"] = solo.new_machine.split(";")[:2] == ["C:\\Program Files\\Python313\\", "C:\\Program Files\\Python313\\Scripts\\"]
already = pd.plan_make_default(r"C:\Program Files\Python313\;C:\Program Files\Python313\Scripts\;C:\a", "", [P313], appdata=APPDATA)
results["already_first_is_not_a_change"] = not already.changed
results["no_pythons_means_no_plan"] = pd.plan_make_default("C:\\a", "", [], appdata=APPDATA) is None

# ---- environment variables in entries are understood
os.environ["RF_TEST_PF"] = r"C:\Program Files"
env_plan = pd.plan_make_default(r"%RF_TEST_PF%\Python311;C:\keep", "", [P313, P311], appdata=APPDATA)
results["entries_with_env_variables_are_matched"] = "Python311" not in env_plan.new_machine and "C:\\keep" in env_plan.new_machine

# ---- the user's own site folders of the NEWEST are left alone
site = pd.plan_make_default(r"C:\Users\Me\AppData\Roaming\Python\Python314\Scripts;C:\a", "", [P314], appdata=APPDATA)
results["newest_user_site_folder_is_not_touched"] = r"C:\Users\Me\AppData\Roaming\Python\Python314\Scripts" in site.new_machine

# ---- discovery returns newest first (whatever is registered here)
found = pd.installed_pythons()
results["discovery_is_sorted_newest_first"] = [p.key for p in found] == sorted((p.key for p in found), reverse=True)

# ---- applying only writes the scopes that changed
written = {}
real_read, real_write = path_backup.read_current_path, path_backup.write_paths
try:
    path_backup.read_current_path = lambda: (machine, plan.new_user)        # user PATH already correct
    path_backup.write_paths = lambda m, u: written.update(machine=m, user=u) or True
    results["apply_writes_the_machine_path"] = pd.apply_plan(plan) is True and written["machine"] == plan.new_machine
    results["apply_leaves_an_unchanged_user_path_alone"] = written["user"] is None
finally:
    path_backup.read_current_path, path_backup.write_paths = real_read, real_write

# ---- write_paths: REG_EXPAND_SZ, skips None, refuses an empty PATH
class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = "HKLM", "HKCU"
    KEY_SET_VALUE, REG_EXPAND_SZ = 2, 2

    def __init__(self):
        self.sets = []

    def OpenKey(self, hive, subkey, reserved=0, access=0):
        return _Key()

    def SetValueEx(self, key, name, reserved, kind, value):
        self.sets.append((kind, value))


real_winreg, real_broadcast = path_backup.winreg, path_backup._broadcast_environment_change
try:
    fake = _FakeWinreg()
    path_backup.winreg = fake
    path_backup._broadcast_environment_change = lambda: None
    results["write_paths_writes_expand_sz"] = path_backup.write_paths("C:\\x", None) is True and fake.sets == [(2, "C:\\x")]
    fake.sets.clear()
    results["write_paths_refuses_an_empty_path"] = path_backup.write_paths("", None) is False and fake.sets == []
    results["write_paths_with_nothing_to_write_is_fine"] = path_backup.write_paths(None, None) is True
finally:
    path_backup.winreg, path_backup._broadcast_environment_change = real_winreg, real_broadcast

# ---- install flags: only the newest series goes on PATH
results["newest_series_is_3_14"] = definitions._NEWEST_PY.ver == "3.14"
captured = []
real_download, real_run_exe = definitions.download, definitions.run_exe
try:
    definitions.download = lambda url, dest, filename, name, *a, **k: Path(dest) / filename
    definitions.run_exe = lambda path, args, name, dry_run=False, **k: captured.append(list(args)) or True
    ctx = InstallContext(temp_dir=tmp, dry_run=True)
    for d in definitions._PY_DEFS:
        definitions._py_install(d, ctx)
    flags = {d.ver: next(a for a in args if a.startswith("PrependPath")) for d, args in zip(definitions._PY_DEFS, captured)}
finally:
    definitions.download, definitions.run_exe = real_download, real_run_exe
results["newest_python_is_prepended_to_path"] = flags["3.14"] == "PrependPath=1"
results["older_pythons_stay_off_path"] = all(flags[v] == "PrependPath=0" for v in ("3.10", "3.11", "3.12", "3.13"))

components = {c.key: c for c in build_components()}
results["only_the_newest_python_is_checked_for_a_path_entry"] = (
    components["python_3.14"].path_entry is not None
    and all(components[f"python_{v}"].path_entry is None for v in ("3.10", "3.11", "3.12", "3.13"))
)
results["older_python_notes_point_at_the_launcher"] = "py -3.12" in components["python_3.12"].note
results["newest_python_note_says_it_is_the_default"] = "first on PATH" in components["python_3.14"].note

# ---- detection follows the registry (custom install folder), not just Program Files
custom = tmp / "CustomPython313"
custom.mkdir()
(custom / "python.exe").write_bytes(b"MZ")
real_pythons = pd.installed_pythons
try:
    pd.installed_pythons = lambda: [PythonInstall("3.13", (3, 13), custom, custom / "python.exe", False)]
    results["custom_folder_python_is_detected"] = components["python_3.13"].is_installed().installed
    results["its_location_is_the_custom_folder"] = components["python_3.13"].location() == custom
    pd.installed_pythons = lambda: []
    results["no_registration_and_no_program_files_copy_is_not_installed"] = (
        definitions._py_dir(definitions._PY_DEFS[0]) == definitions.PROGRAM_FILES / "Python310"
    )
finally:
    pd.installed_pythons = real_pythons

# ---- the menu action
from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
if window.scan_worker is not None:
    window.scan_worker.wait()
    app.processEvents()
window._save_settings = lambda: None
results["menu_has_the_action"] = window.python_default_action.text().startswith("Make the newest Python the default")

calls = {"backup": 0, "applied": 0, "dialogs": []}
real = {
    "installed": pd.installed_pythons, "read": path_backup.read_current_path, "backup": path_backup.create_backup,
    "apply": pd.apply_plan, "exec": QMessageBox.exec, "info": QMessageBox.information, "warn": QMessageBox.warning,
}
try:
    pd.installed_pythons = lambda: [P314, P313, P311]
    path_backup.read_current_path = lambda: (machine, user)
    path_backup.create_backup = lambda app_dir, reason: calls.__setitem__("backup", calls["backup"] + 1) or Path("x")
    pd.apply_plan = lambda plan: calls.__setitem__("applied", calls["applied"] + 1) or True
    QMessageBox.information = staticmethod(lambda parent, title, text, *a, **k: calls["dialogs"].append((title, text)))
    QMessageBox.warning = staticmethod(lambda parent, title, text, *a, **k: calls["dialogs"].append((title, text)))

    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    window._on_make_python_default()
    results["declining_changes_nothing"] = calls["backup"] == 0 and calls["applied"] == 0

    seen = {}

    def accept(self):
        seen["text"], seen["info"], seen["detail"] = self.text(), self.informativeText(), self.detailedText()
        return QMessageBox.StandardButton.Yes

    QMessageBox.exec = accept
    window._on_make_python_default()
    results["confirm_dialog_names_the_new_default"] = "3.14" in seen["text"] and "E:\\Python314" in seen["info"]
    results["confirm_dialog_lists_every_change"] = "Remove from PATH (machine)" in seen["detail"] and "Put first on PATH (machine)" in seen["detail"]
    results["confirm_dialog_promises_the_launcher_still_works"] = "py -3.12" in seen["info"]
    results["accepting_backs_up_first_then_applies"] = calls["backup"] == 1 and calls["applied"] == 1
    results["success_is_reported"] = calls["dialogs"] and calls["dialogs"][-1][0] == "Python Default Updated"

    pd.apply_plan = lambda plan: False
    window._on_make_python_default()
    results["a_refused_write_is_reported_as_needing_admin"] = calls["dialogs"][-1][0] == "Could Not Change PATH" and "administrator" in calls["dialogs"][-1][1]

    # already the default -> just says so
    path_backup.read_current_path = lambda: (plan.new_machine, plan.new_user)
    n = calls["backup"]
    window._on_make_python_default()
    results["already_default_says_so_and_does_not_back_up"] = calls["dialogs"][-1][0] == "Already the Default" and calls["backup"] == n

    pd.installed_pythons = lambda: []
    window._on_make_python_default()
    results["no_python_installed_says_so"] = calls["dialogs"][-1][0] == "No Python Found"
finally:
    pd.installed_pythons, path_backup.read_current_path, path_backup.create_backup = real["installed"], real["read"], real["backup"]
    pd.apply_plan, QMessageBox.exec, QMessageBox.information, QMessageBox.warning = real["apply"], real["exec"], real["info"], real["warn"]

window.close()
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
