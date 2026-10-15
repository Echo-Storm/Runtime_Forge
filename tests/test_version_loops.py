"""
Tests for the "it always says update available" fixes (newest-folder detection,
OpenAL actually applying updates, LLVM on PATH), the JDK-off-PATH install flags,
and "make the newest Java the default" (core/java_default.py).

Offline and side-effect free.

Run directly:
    venv\\Scripts\\python.exe tests\\test_version_loops.py
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication, QMessageBox

from core import checks, definitions, java_default as jd, path_backup
from core.definitions import InstalledState, InstallContext, build_components
from core.logger import setup_logging
from core.version_resolvers import LatestInfo

tmp = Path(tempfile.mkdtemp(prefix="rf_loops_"))
setup_logging(tmp)
results = {}


def make_dirs(base: Path, names):
    for n in names:
        (base / n).mkdir(parents=True, exist_ok=True)


# ---- A: side-by-side installs -> the NEWEST counts
shared = tmp / "shared"
make_dirs(shared, ["10.0.11", "10.0.13", "10.0.9", "9.0.21", "8.0.32"])
results["picks_highest_patch_not_first_listed"] = checks.any_child_dir_matches(str(shared), "10.0.").name == "10.0.13"
results["numeric_not_alphabetical_order"] = checks.any_child_dir_matches(str(shared), "10.0.").name != "10.0.9"
results["prefix_still_filters"] = checks.any_child_dir_matches(str(shared), "9.").name == "9.0.21"
results["no_match_is_none"] = checks.any_child_dir_matches(str(shared), "11.") is None
results["missing_base_is_none"] = checks.any_child_dir_matches(str(tmp / "nope"), "x") is None
adopt = tmp / "adoptium"
make_dirs(adopt, ["jdk-21.0.9.10-hotspot", "jdk-21.0.12.8-hotspot", "jdk-17.0.20.8-hotspot"])
results["jdk_folders_newest_by_numbers"] = checks.any_child_dir_matches(str(adopt), "jdk-21").name == "jdk-21.0.12.8-hotspot"

real_root, real_sdk, real_adopt = definitions._DOTNET_SHARED_ROOT, definitions._DOTNET_SDK_ROOT, definitions._ADOPTIUM_ROOT
try:
    fx = tmp / "dotnet" / "shared"
    make_dirs(fx / "Microsoft.AspNetCore.App", ["10.0.11", "10.0.13"])
    sdk = tmp / "dotnet" / "sdk"
    make_dirs(sdk, ["10.0.303", "10.0.402", "8.0.426"])
    definitions._DOTNET_SHARED_ROOT, definitions._DOTNET_SDK_ROOT, definitions._ADOPTIUM_ROOT = fx, sdk, adopt
    nd = next(d for d in definitions._NET_DEFS if d.name == ".NET 10 ASP.NET Core Runtime")
    results["dotnet_runtime_reads_the_newest_installed"] = definitions._net_is_installed(nd).version == "10.0.13"
    results["dotnet_sdk_reads_the_newest_installed"] = definitions._net_sdk_is_installed(definitions._NetSdkDef("10.0")).version == "10.0.402"
    results["an_updated_dotnet_is_no_longer_outdated"] = not definitions.version_is_newer("10.0.13", definitions._net_is_installed(nd).version)
    jd21 = next(j for j in definitions._JDK_DEFS if j.feature_version == 21)
    results["jdk_state_reads_the_newest_build"] = definitions._jdk_is_installed(jd21).version == "21.0.12.8"
    results["jdk_path_entry_is_the_newest_bin"] = definitions._jdk_path_entry(jd21).parent.name == "jdk-21.0.12.8-hotspot"
finally:
    definitions._DOTNET_SHARED_ROOT, definitions._DOTNET_SDK_ROOT, definitions._ADOPTIUM_ROOT = real_root, real_sdk, real_adopt

# ---- B: OpenAL applies updates (and Reinstall), and only when needed
calls = []
real = (definitions._openal_has_legacy_key, definitions._openal_dll_is_soft, definitions._openal_resolve_latest,
        definitions._openal_install_legacy_step, definitions._openal_install_soft_step)
try:
    definitions._openal_resolve_latest = lambda: LatestInfo("1.25.2", "u", "f")
    definitions._openal_install_legacy_step = lambda ctx: calls.append("legacy") or True
    definitions._openal_install_soft_step = lambda ctx: calls.append("soft") or True

    def run(has_key, soft_version, force=False):
        calls.clear()
        definitions._openal_has_legacy_key = lambda: has_key
        definitions._openal_dll_is_soft = lambda: soft_version
        ok = definitions._openal_install(InstallContext(temp_dir=tmp, force=force))
        return ok, list(calls)

    results["openal_older_soft_gets_updated"] = run(True, "1.25.1") == (True, ["soft"])
    results["openal_current_is_left_alone"] = run(True, "1.25.2") == (True, [])
    results["openal_newer_than_latest_is_left_alone"] = run(True, "1.26.0") == (True, [])
    results["openal_reinstall_forces_it"] = run(True, "1.25.2", force=True) == (True, ["soft"])
    results["openal_missing_soft_installs_it"] = run(True, None) == (True, ["soft"])
    results["openal_missing_key_plants_it"] = run(False, "1.25.2") == (True, ["legacy"])
    results["openal_fresh_machine_does_both"] = run(False, None) == (True, ["legacy", "soft"])
    definitions._openal_install_soft_step = lambda ctx: False
    results["openal_failed_copy_is_a_failure"] = run(True, "1.25.1")[0] is False
finally:
    (definitions._openal_has_legacy_key, definitions._openal_dll_is_soft, definitions._openal_resolve_latest,
     definitions._openal_install_legacy_step, definitions._openal_install_soft_step) = real

# ---- the worker hands Reinstall's force flag to the install
from ui.workers import InstallWorker

seen = {}
comp = definitions.Component("probe", "Probe", "Test", lambda: InstalledState(True, "1.0"),
                             lambda ctx: seen.setdefault("force", ctx.force) is not None or True)
worker = InstallWorker([comp], {"probe"}, True, None, force=True)
worker._run(__import__("core.logger", fromlist=["get_logger"]).get_logger())
results["reinstall_force_reaches_the_installer"] = seen.get("force") is True

# ---- C: LLVM adds itself to PATH (its silent mode skips that page)
added = []
real_add, real_run_exe, real_dl = path_backup.add_directory_to_path, definitions.run_exe, definitions.download
try:
    path_backup.add_directory_to_path = lambda p: added.append(p) or True
    definitions.run_exe = lambda *a, **k: True
    definitions.download = lambda url, dest, name, *a, **k: Path(dest) / name
    definitions._llvm_resolve_latest = lambda: LatestInfo("22.1.8", "u", "LLVM-22.1.8-win64.exe", "aa" * 32)
    results["llvm_install_succeeds"] = definitions._llvm_install(InstallContext(temp_dir=tmp)) is True
    results["llvm_bin_is_added_to_path"] = added == [definitions._LLVM_EXE.parent]
    added.clear()
    definitions._llvm_install(InstallContext(temp_dir=tmp, dry_run=True))
    results["llvm_dry_run_leaves_path_alone"] = added == []
    definitions.run_exe = lambda *a, **k: False
    added.clear()
    results["llvm_failed_install_does_not_touch_path"] = definitions._llvm_install(InstallContext(temp_dir=tmp)) is False and added == []
finally:
    path_backup.add_directory_to_path, definitions.run_exe, definitions.download = real_add, real_run_exe, real_dl

# ---- D: only the newest JDK takes over PATH
msi_args = {}
real_run_msi, real_dl = definitions.run_msi, definitions.download
try:
    definitions.run_msi = lambda path, args, name, dry_run=False, **k: msi_args.__setitem__(name, list(args)) or True
    definitions.download = lambda url, dest, name, *a, **k: Path(dest) / name
    definitions._jdk_resolve_latest = lambda jd: LatestInfo("1.0", "u", "x.msi", "bb" * 32)
    for d in definitions._JDK_DEFS:
        definitions._jdk_install(d, InstallContext(temp_dir=tmp))
finally:
    definitions.run_msi, definitions.download = real_run_msi, real_dl
results["newest_jdk_is_21"] = definitions._NEWEST_JDK.feature_version == 21
results["newest_jdk_keeps_the_path_feature"] = any("INSTALLLEVEL=1" in a for a in msi_args["Temurin JDK 21"]) and not any(a.startswith("ADDLOCAL") for a in msi_args["Temurin JDK 21"])
for name in ("Temurin JDK 17", "Temurin JDK 8"):
    addlocal = next(a for a in msi_args[name] if a.startswith("ADDLOCAL"))
    results[f"{name.split()[-1]}_stays_off_path"] = "FeatureEnvironment" not in addlocal and "FeatureMain" in addlocal

# ---- Java default: plan
PF = "C:\\Program Files\\Eclipse Adoptium"
J21 = jd.JavaInstall("jdk-21.0.12.8-hotspot", (21, 0, 12, 8), Path(PF) / "jdk-21.0.12.8-hotspot", True)
J17 = jd.JavaInstall("jdk-17.0.20.8-hotspot", (17, 0, 20, 8), Path(PF) / "jdk-17.0.20.8-hotspot", True)
J8 = jd.JavaInstall("jdk-8.0.504.1-hotspot", (8, 0, 504, 1), Path(PF) / "jdk-8.0.504.1-hotspot", True)
JRE = jd.JavaInstall("jre-21.0.11.10-hotspot", (21, 0, 11, 10), Path(PF) / "jre-21.0.11.10-hotspot", False)
machine = ";".join([PF + "\\jdk-8.0.504.1-hotspot\\bin", "C:\\Windows\\system32", PF + "\\jdk-17.0.20.8-hotspot\\bin",
                    PF + "\\jdk-21.0.12.8-hotspot\\bin", PF + "\\jre-21.0.11.10-hotspot\\bin", "C:\\Program Files\\Git\\cmd"])
plan = jd.plan_make_default(machine, "C:\\u", [J21, J17, J8, JRE], PF + "\\jre-21.0.11.10-hotspot\\", None, root=Path(PF))
new = plan.new_machine.split(";")
results["java_newest_jdk_is_chosen"] = plan.latest.name == "jdk-21.0.12.8-hotspot"
results["java_newest_goes_first"] = new[0] == PF + "\\jdk-21.0.12.8-hotspot\\bin"
results["java_other_jdks_and_jres_are_removed"] = not any(x in plan.new_machine for x in ("jdk-8", "jdk-17", "jre-21"))
results["java_unrelated_entries_keep_their_order"] = new[1:] == ["C:\\Windows\\system32", "C:\\Program Files\\Git\\cmd"]
results["java_home_pointing_at_a_jre_is_repointed_to_the_jdk"] = plan.java_home_machine == PF + "\\jdk-21.0.12.8-hotspot"
results["java_unset_user_java_home_is_left_unset"] = plan.java_home_user is None
foreign = jd.plan_make_default(machine, "", [J21, J17], "D:\\tools\\my-jdk", None, root=Path(PF))
results["java_home_elsewhere_is_never_touched"] = foreign.java_home_machine is None
again = jd.plan_make_default(plan.new_machine, plan.new_user, [J21, J17, J8, JRE], plan.java_home_machine, None, root=Path(PF))
results["java_second_run_changes_nothing"] = not again.changed
results["java_no_jdk_means_no_plan"] = jd.plan_make_default(machine, "", [JRE], None, None, root=Path(PF)) is None
results["java_discovery_ignores_folders_without_java_exe"] = jd.installed_javas(adopt) == []
(adopt / "jdk-21.0.12.8-hotspot" / "bin").mkdir()
(adopt / "jdk-21.0.12.8-hotspot" / "bin" / "java.exe").write_bytes(b"MZ")
results["java_discovery_finds_real_installs"] = [j.name for j in jd.installed_javas(adopt)] == ["jdk-21.0.12.8-hotspot"]

# ---- env var helpers + apply
class _Key:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = "HKLM", "HKCU", 2, 1

    def __init__(self):
        self.sets = []

    def OpenKey(self, hive, subkey, reserved=0, access=0):
        return _Key()

    def SetValueEx(self, key, name, reserved, kind, value):
        self.sets.append((name, kind, value))


real_winreg, real_bc = path_backup.winreg, path_backup._broadcast_environment_change
try:
    fake = _FakeWinreg()
    path_backup.winreg = fake
    path_backup._broadcast_environment_change = lambda: None
    results["write_env_var_sets_reg_sz"] = path_backup.write_env_var("machine", "JAVA_HOME", "C:\\j") is True and fake.sets == [("JAVA_HOME", 1, "C:\\j")]
    results["write_env_var_refuses_empty"] = path_backup.write_env_var("user", "JAVA_HOME", " ") is False
finally:
    path_backup.winreg, path_backup._broadcast_environment_change = real_winreg, real_bc

written = {}
real_read, real_w, real_ev = path_backup.read_current_path, path_backup.write_paths, path_backup.write_env_var
try:
    path_backup.read_current_path = lambda: (machine, "C:\\u")
    path_backup.write_paths = lambda m, u: written.update(paths=(m, u)) or True
    path_backup.write_env_var = lambda scope, name, value: written.setdefault("env", []).append((scope, name, value)) or True
    results["java_apply_writes_path_and_java_home"] = jd.apply_plan(plan) is True and written["paths"] == (plan.new_machine, None) and written["env"] == [("machine", "JAVA_HOME", plan.java_home_machine)]
finally:
    path_backup.read_current_path, path_backup.write_paths, path_backup.write_env_var = real_read, real_w, real_ev

# ---- the menu action
from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
if window.scan_worker is not None:
    window.scan_worker.wait()
    app.processEvents()
window._save_settings = lambda: None
results["java_menu_action_exists"] = window.java_default_action.text().startswith("Make the newest Java the default")

dialogs, steps = [], {"backup": 0, "applied": 0}
saved = (jd.installed_javas, path_backup.read_current_path, path_backup.read_env_var, path_backup.create_backup, jd.apply_plan,
         QMessageBox.exec, QMessageBox.information, QMessageBox.warning)
try:
    jd.installed_javas = lambda: [J21, J17, J8, JRE]
    path_backup.read_current_path = lambda: (machine, "C:\\u")
    path_backup.read_env_var = lambda scope, name: (PF + "\\jre-21.0.11.10-hotspot\\") if scope == "machine" else None
    path_backup.create_backup = lambda app_dir, reason: steps.__setitem__("backup", steps["backup"] + 1) or Path("x")
    jd.apply_plan = lambda plan_: steps.__setitem__("applied", steps["applied"] + 1) or True
    QMessageBox.information = staticmethod(lambda parent, title, text, *a, **k: dialogs.append((title, text)))
    QMessageBox.warning = staticmethod(lambda parent, title, text, *a, **k: dialogs.append((title, text)))
    seen_dialog = {}

    QMessageBox.exec = lambda self: QMessageBox.StandardButton.No
    window._on_make_java_default()
    results["java_declining_changes_nothing"] = steps == {"backup": 0, "applied": 0}

    def accept(self):
        seen_dialog.update(text=self.text(), info=self.informativeText(), detail=self.detailedText())
        return QMessageBox.StandardButton.Yes

    QMessageBox.exec = accept
    window._on_make_java_default()
    results["java_confirm_names_the_jdk_and_lists_changes"] = (
        "jdk-21.0.12.8" in seen_dialog["text"] and "Remove from PATH" in seen_dialog["detail"] and "Set JAVA_HOME (machine)" in seen_dialog["detail"])
    results["java_accepting_backs_up_then_applies"] = steps == {"backup": 1, "applied": 1} and dialogs[-1][0] == "Java Default Updated"
    jd.apply_plan = lambda plan_: False
    window._on_make_java_default()
    results["java_refused_write_mentions_administrator"] = dialogs[-1][0] == "Could Not Change PATH" and "administrator" in dialogs[-1][1]
    path_backup.read_current_path = lambda: (plan.new_machine, "C:\\u")
    path_backup.read_env_var = lambda scope, name: plan.java_home_machine if scope == "machine" else None
    window._on_make_java_default()
    results["java_already_default_says_so"] = dialogs[-1][0] == "Already the Default"
    jd.installed_javas = lambda: [JRE]
    window._on_make_java_default()
    results["java_no_jdk_says_so"] = dialogs[-1][0] == "No JDK Found"
finally:
    (jd.installed_javas, path_backup.read_current_path, path_backup.read_env_var, path_backup.create_backup, jd.apply_plan,
     QMessageBox.exec, QMessageBox.information, QMessageBox.warning) = saved

window.close()
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
