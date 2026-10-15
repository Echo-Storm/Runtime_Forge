"""
Tests for core/catalog.py (the extra components: Terminal, legacy game
support, Go, Rust, uv, Ghidra, MSYS2, Inno Setup, Chrome, Discord, AnyDesk,
Claude) and the "optional" behavior in the window.

Everything here is offline: network calls, winget, dism and the registry are
replaced with fakes.

Run directly:
    venv\\Scripts\\python.exe tests\\test_catalog.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core import catalog, checks, definitions, http_cache
from core.definitions import CATEGORY_ORDER, InstalledState, InstallContext, build_components
from core.downloader import Trust
from core.logger import setup_logging
from core.version_resolvers import LatestInfo

tmp = Path(tempfile.mkdtemp(prefix="rf_catalog_"))
setup_logging(tmp)
results = {}

components = {c.key: c for c in build_components()}
catalog_keys = ["terminal", "directplay", "xna40", "physx", "uv", "go", "rust", "ghidra",
                "msys2", "innosetup", "chrome", "discord", "anydesk", "claude",
                "firefox", "edge", "onedrive", "windowsapp", "steam", "epic", "klite", "irfanview",
                "notepadpp", "sublime"]

# ---- registry shape
results["all_catalog_components_registered"] = all(k in components for k in catalog_keys)
results["keys_are_unique"] = len({c.key for c in build_components()}) == len(build_components())
cats = {k: components[k].category for k in catalog_keys}
results["categories_as_designed"] = cats == {
    "terminal": "Dev Tools", "directplay": "Legacy Game Support", "xna40": "Legacy Game Support",
    "physx": "Legacy Game Support", "uv": "Python", "go": "Go & Rust", "rust": "Go & Rust",
    "ghidra": "Dev Tools", "msys2": "Dev Tools", "innosetup": "Dev Tools", "chrome": "Apps",
    "discord": "Apps", "anydesk": "Apps", "claude": "Apps",
    "firefox": "Apps", "edge": "Apps", "onedrive": "Apps", "windowsapp": "Apps", "steam": "Apps",
    "epic": "Apps", "klite": "Apps", "irfanview": "Apps", "notepadpp": "Dev Tools", "sublime": "Dev Tools",
}
order = [CATEGORY_ORDER.index(c.category) if c.category in CATEGORY_ORDER else 99 for c in build_components()]
results["components_come_out_grouped_in_category_order"] = order == sorted(order)
results["optional_flags"] = (
    all(components[k].optional for k in ("uv", "go", "rust", "ghidra", "msys2", "innosetup", "chrome", "discord", "anydesk", "claude", "physx"))
    and not any(components[k].optional for k in ("terminal", "directplay", "xna40"))
)
results["every_catalog_component_has_a_note_or_is_plain"] = all(isinstance(components[k].note, str) for k in catalog_keys)
results["winget_backed_components_say_so"] = all(
    "winget" in components[k].note.lower()
    for k in ("discord", "anydesk", "claude", "msys2", "innosetup", "physx", "firefox", "edge", "onedrive",
              "windowsapp", "steam", "epic", "klite", "irfanview", "notepadpp", "sublime")
)
results["edge_cannot_be_uninstalled_from_the_app"] = components["edge"].uninstall is None
results["other_winget_apps_can_be_uninstalled"] = all(components[k].uninstall is not None for k in ("firefox", "steam", "notepadpp"))
results["new_apps_are_optional"] = all(components[k].optional for k in (
    "firefox", "edge", "onedrive", "windowsapp", "steam", "epic", "klite", "irfanview", "notepadpp", "sublime"))
results["vscode_can_be_uninstalled_now"] = components["vscode"].uninstall is not None

# ---- Appx package lookup (fake registry, no machine state)
class _FakeKey:
    def __init__(self, names):
        self.names = names

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = object()

    def __init__(self, names):
        self._names = names

    def OpenKey(self, *_a):
        return _FakeKey(self._names)

    def EnumKey(self, key, i):
        if i >= len(key.names):
            raise OSError
        return key.names[i]


real_winreg = checks.winreg
try:
    checks.winreg = _FakeWinreg([
        "Microsoft.WindowsTerminal_1.23.0.0_x64__8wekyb3d8bbwe",
        "Microsoft.WindowsTerminal_1.24.12741.0_x64__8wekyb3d8bbwe",
        "Microsoft.WindowsTerminalPreview_1.99.0.0_x64__8wekyb3d8bbwe",
        "Microsoft.WindowsTerminal_9.9.9.9_x64__someoneelse",
        "Claude_2.37337.1.0_x64__pzs8sxrjxfjjc",
    ])
    results["appx_picks_highest_matching_version"] = checks.appx_package_version("Microsoft.WindowsTerminal", "8wekyb3d8bbwe") == "1.24.12741.0"
    results["appx_ignores_preview_and_other_publishers"] = checks.appx_package_version("Microsoft.WindowsTerminal", "8wekyb3d8bbwe") != "9.9.9.9"
    results["appx_finds_claude"] = checks.appx_package_version("Claude", "pzs8sxrjxfjjc") == "2.37337.1.0"
    results["appx_missing_is_none"] = checks.appx_package_version("Nope", "xyz") is None
finally:
    checks.winreg = real_winreg

# ---- Programs-and-Features parsing (AnyDesk's version reads "ad 9.7.3")
real_find = checks.find_uninstall_entry_by_display_name
try:
    checks.find_uninstall_entry_by_display_name = lambda pattern: "ad 9.7.3"
    results["entry_state_extracts_numeric_version"] = catalog._entry_state("x") == InstalledState(True, "9.7.3")
    checks.find_uninstall_entry_by_display_name = lambda pattern: None
    results["entry_state_missing_is_not_installed"] = not catalog._entry_state("x").installed
finally:
    checks.find_uninstall_entry_by_display_name = real_find

# ---- DirectPlay: the servicing stack's record decides, not a DLL that lingers
class _CbsKey:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeCbsWinreg:
    HKEY_LOCAL_MACHINE = object()

    def __init__(self, packages):
        self.packages = packages     # name -> CurrentState

    def OpenKey(self, parent, name=None):
        if isinstance(parent, _CbsKey) or name is not None and name in self.packages:
            return _CbsKey(self.packages[name])
        return _CbsKey(None)

    def EnumKey(self, key, i):
        names = list(self.packages)
        if i >= len(names):
            raise OSError
        return names[i]

    def QueryValueEx(self, key, value_name):
        return (key.state, 4)


real_winreg = checks.winreg
try:
    pkg = "Microsoft-Windows-DirectPlay-OC-Package~31bf3856ad364e35~amd64~~10.0.26100.4202"
    other = "Microsoft-Windows-Something-Else~31bf3856ad364e35~amd64~~10.0.26100.1"
    checks.winreg = _FakeCbsWinreg({pkg: 112, other: 112})
    results["cbs_installed_package_reports_true"] = checks.cbs_package_state(catalog._DIRECTPLAY_PACKAGE) is True
    checks.winreg = _FakeCbsWinreg({pkg: 64, other: 112})
    results["cbs_staged_only_package_reports_false"] = checks.cbs_package_state(catalog._DIRECTPLAY_PACKAGE) is False
    checks.winreg = _FakeCbsWinreg({other: 112})
    results["cbs_no_matching_package_is_none"] = checks.cbs_package_state(catalog._DIRECTPLAY_PACKAGE) is None

    real_state = checks.cbs_package_state
    checks.cbs_package_state = lambda pattern: True
    results["directplay_installed_when_feature_enabled"] = catalog._directplay_state().installed
    checks.cbs_package_state = lambda pattern: False
    results["directplay_not_installed_when_feature_off_even_if_dll_lingers"] = not catalog._directplay_state().installed
    checks.cbs_package_state = real_state
finally:
    checks.winreg = real_winreg

# ---- VC++ 2015-2022 detection understands the "v14" display names
captured_patterns = []
real_reg_value, real_find_dep = checks.reg_value, checks.find_dependency_by_display_name
try:
    checks.reg_value = lambda *a, **k: None
    checks.find_dependency_by_display_name = lambda pattern: captured_patterns.append(pattern) or "14.50.35719.0"
    state = definitions._vc_is_installed(next(v for v in definitions._VC_DEFS if v.key == "2015-2022_x64"))
    pattern = captured_patterns[-1]
    results["vc_2015_2022_found_via_dependencies"] = state == InstalledState(True, "14.50.35719.0")
    results["vc_pattern_matches_new_v14_name"] = bool(pattern.search("Microsoft Visual C++ v14 Redistributable (x64) - 14.50.35719"))
    results["vc_pattern_matches_classic_2015_2022_name"] = bool(pattern.search("Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.38.33135"))
    results["vc_pattern_ignores_additional_runtime_entries"] = not pattern.search("Microsoft Visual C++ 2022 X64 Additional Runtime - 14.50.35719")
    results["vc_pattern_ignores_the_other_architecture"] = not pattern.search("Microsoft Visual C++ v14 Redistributable (x86) - 14.50.35719")
    definitions._vc_is_installed(next(v for v in definitions._VC_DEFS if v.key == "2012_x86"))
    old_pattern = captured_patterns[-1]
    results["older_years_still_match_their_own_names"] = bool(old_pattern.search("Microsoft Visual C++ 2012 Redistributable (x86) - 11.0.61030")) and not old_pattern.search("Microsoft Visual C++ 2013 Redistributable (x86) - 12.0.40664")
finally:
    checks.reg_value, checks.find_dependency_by_display_name = real_reg_value, real_find_dep

# ---- winget list parsing (Windows App has no registry trail we can read)
class _ListResult:
    def __init__(self, out):
        self.stdout, self.returncode = out, 0


real_run, real_on_path = subprocess.run, checks.command_on_path
try:
    checks.command_on_path = lambda name: r"C:\fake\winget.exe"
    subprocess.run = lambda *a, **k: _ListResult("Name        Id                    Version\n----\nWindows App Microsoft.WindowsApp 2.0.1482.0\n")
    results["winget_list_finds_installed_package_and_version"] = catalog._winget_list_state("Microsoft.WindowsApp") == InstalledState(True, "2.0.1482.0")
    subprocess.run = lambda *a, **k: _ListResult("No installed package found matching input criteria.\n")
    results["winget_list_missing_package_is_not_installed"] = not catalog._winget_list_state("Microsoft.WindowsApp").installed
    checks.command_on_path = lambda name: None
    results["winget_list_without_winget_is_not_installed"] = not catalog._winget_list_state("Microsoft.WindowsApp").installed
finally:
    subprocess.run, checks.command_on_path = real_run, real_on_path

# ---- GitHub resolver: asset match, version from tag, fallback on failure
import re


class _Resp:
    def __init__(self, payload=None, text="", ok=True):
        self._payload, self.text, self.ok = payload, text, ok

    def raise_for_status(self):
        if not self.ok:
            raise OSError("boom")

    def json(self):
        return self._payload


real_get = http_cache.get
try:
    http_cache.get = lambda *a, **k: _Resp({"tag_name": "v1.2.3", "assets": [
        {"name": "other.zip", "browser_download_url": "u0"},
        {"name": "tool-win.zip", "browser_download_url": "https://x/tool-win.zip", "digest": "sha256:" + "ab" * 32},
    ]})
    got = catalog._github_latest("o/r", re.compile(r"^tool-win\.zip$"), lambda t: t.lstrip("v"))
    results["github_latest_matches_asset_and_version"] = (got.version, got.url, got.sha256) == ("1.2.3", "https://x/tool-win.zip", "ab" * 32)
    fb = LatestInfo("0.0.1", "fb", "fb.zip", "cd" * 32)
    http_cache.get = lambda *a, **k: _Resp(ok=False)
    results["github_latest_falls_back_when_api_fails"] = catalog._github_latest("o/r", re.compile("x"), lambda t: t, fb) is fb
    try:
        catalog._github_latest("o/r", re.compile("x"), lambda t: t)
        results["github_latest_raises_without_fallback"] = False
    except Exception:
        results["github_latest_raises_without_fallback"] = True

    # Go: go.dev JSON
    http_cache.get = lambda *a, **k: _Resp([{"version": "go1.30.1", "files": [
        {"os": "windows", "arch": "amd64", "kind": "archive", "filename": "go1.30.1.windows-amd64.zip", "sha256": "11"},
        {"os": "windows", "arch": "amd64", "kind": "installer", "filename": "go1.30.1.windows-amd64.msi", "sha256": "22" * 32},
        {"os": "linux", "arch": "amd64", "kind": "archive", "filename": "go1.30.1.linux-amd64.tar.gz", "sha256": "33"},
    ]}])
    g = catalog._go_resolve()
    results["go_resolver_reads_godev_json"] = (g.version, g.filename, g.sha256, g.url) == (
        "1.30.1", "go1.30.1.windows-amd64.msi", "22" * 32, "https://go.dev/dl/go1.30.1.windows-amd64.msi")

    # Rust: channel toml + rustup-init sha256 file
    def rust_get(url, *a, **k):
        if url.endswith("channel-rust-stable.toml"):
            return _Resp(text='[pkg.cargo]\nversion = "0.1.0"\n[pkg.rust]\nversion = "1.99.0 (b940084d7 2026-09-28)"\n')
        return _Resp(text="DEADBEEF" + "0" * 56 + "  rustup-init.exe\n")
    http_cache.get = rust_get
    r = catalog._rust_resolve()
    results["rust_resolver_reads_stable_version"] = r.version == "1.99.0"
    results["rust_resolver_reads_rustup_sha256"] = r.sha256 == ("deadbeef" + "0" * 56)
    results["rust_cache_name_changes_with_hash"] = r.filename == f"rustup-init-{r.sha256[:12]}.exe"
finally:
    http_cache.get = real_get

# ---- every downloading install passes a Trust (hash and/or signer) to download()
captured = {}


def fake_download(url, dest_dir, filename, name, dry_run=False, progress_cb=None, trust=None):
    captured[name] = trust
    return dest_dir / filename


def latest(version="1.0", sha="ee" * 32):
    return LatestInfo(version, f"https://example.test/{version}/file.bin", "file.bin", sha)


real_download, real_resolvers = catalog.download, (catalog._terminal_resolve, catalog._go_resolve, catalog._rust_resolve, catalog._uv_resolve, catalog._ghidra_resolve)
try:
    catalog.download = fake_download
    catalog._terminal_resolve = catalog._go_resolve = catalog._rust_resolve = catalog._uv_resolve = catalog._ghidra_resolve = latest
    ctx = InstallContext(temp_dir=tmp, dry_run=True)
    for key in ("terminal", "xna40", "chrome", "go", "rust", "uv", "ghidra"):
        captured.clear()
        components[key].install(ctx)
        trusts = list(captured.values())
        results[f"{key}_install_requests_integrity_checks"] = bool(trusts) and all(isinstance(t, Trust) and (t.sha256 or t.publishers) for t in trusts)
finally:
    catalog.download = real_download
    (catalog._terminal_resolve, catalog._go_resolve, catalog._rust_resolve, catalog._uv_resolve, catalog._ghidra_resolve) = real_resolvers

# publishers pinned where the vendor signs
captured.clear()
try:
    catalog.download = fake_download
    catalog._go_resolve = latest
    components["go"].install(InstallContext(temp_dir=tmp, dry_run=True))
    results["go_pins_google_as_signer"] = "Google" in next(iter(captured.values())).publishers
finally:
    catalog.download = real_download
    catalog._go_resolve = real_resolvers[1]

# ---- winget-backed installs
calls = []


class _Done:
    def __init__(self, code=0, out="Successfully installed\n"):
        self.returncode, self.stdout = code, out


real_run, real_on_path = subprocess.run, checks.command_on_path
try:
    subprocess.run = lambda args, **kw: (calls.append(list(args)), _Done())[1]
    checks.command_on_path = lambda name: r"C:\fake\winget.exe"
    ok = components["discord"].install(InstallContext(temp_dir=tmp))
    cmd = calls[-1]
    results["winget_install_command_is_exact_and_silent"] = (
        ok and cmd[0].endswith("winget.exe") and cmd[1:4] == ["install", "--id", "Discord.Discord"]
        and "-e" in cmd and "--silent" in cmd and "--accept-package-agreements" in cmd and "--disable-interactivity" in cmd
    )
    components["discord"].uninstall(InstallContext(temp_dir=tmp))
    results["winget_uninstall_command"] = calls[-1][1:4] == ["uninstall", "--id", "Discord.Discord"] and "--silent" in calls[-1]

    n = len(calls)
    results["winget_dry_run_runs_nothing"] = components["claude"].install(InstallContext(temp_dir=tmp, dry_run=True)) and len(calls) == n

    subprocess.run = lambda args, **kw: (calls.append(list(args)), _Done(code=1, out="boom"))[1]
    results["winget_failure_exit_code_is_a_failure"] = components["anydesk"].install(InstallContext(temp_dir=tmp)) is False

    checks.command_on_path = lambda name: None
    n = len(calls)
    results["winget_missing_fails_clearly_without_running_anything"] = components["msys2"].install(InstallContext(temp_dir=tmp)) is False and len(calls) == n

    # dism features
    checks.command_on_path = real_on_path
    subprocess.run = lambda args, **kw: (calls.append(list(args)), _Done())[1]
    components["directplay"].install(InstallContext(temp_dir=tmp))
    enable = calls[-1]
    components["directplay"].uninstall(InstallContext(temp_dir=tmp))
    disable = calls[-1]
    results["directplay_enable_uses_dism_all_norestart"] = (
        enable[0].lower() == "dism.exe" and "/enable-feature" in enable and "/featurename:DirectPlay" in enable
        and "/All" in enable and "/NoRestart" in enable
    )
    results["directplay_disable_uses_dism"] = "/disable-feature" in disable and "/All" not in disable
finally:
    subprocess.run = real_run
    checks.command_on_path = real_on_path

# ---- portable installs: Ghidra detection, uv extraction
ghidra_root = tmp / "Ghidra"
for name in ("ghidra_11.0_PUBLIC", "ghidra_12.1.4_PUBLIC", "ghidra_9.2_PUBLIC", "not_ghidra"):
    (ghidra_root / name).mkdir(parents=True)
    if name != "not_ghidra":
        (ghidra_root / name / "ghidraRun.bat").write_text("@echo off")
(ghidra_root / "ghidra_12.1.4_PUBLIC").joinpath("ghidraRun.bat").write_text("@echo off")
real_dir = catalog._GHIDRA_DIR
try:
    catalog._GHIDRA_DIR = ghidra_root
    state = catalog._ghidra_state()
    results["ghidra_detection_picks_newest_with_launcher"] = state.installed and state.version == "12.1.4"
    results["ghidra_location_is_its_folder"] = catalog._ghidra_location() == ghidra_root / "ghidra_12.1.4_PUBLIC"
    results["ghidra_ignores_folders_without_launcher"] = len(catalog._ghidra_installs()) == 3
    removed = components["ghidra"].uninstall(InstallContext(temp_dir=tmp))
    results["ghidra_uninstall_removes_every_version_but_nothing_else"] = (
        removed and not list(ghidra_root.glob("ghidra_*")) and (ghidra_root / "not_ghidra").is_dir()
    )
    results["ghidra_missing_is_not_installed"] = not catalog._ghidra_state().installed
    (ghidra_root / "not_ghidra").rmdir()
    components["ghidra"].uninstall(InstallContext(temp_dir=tmp, dry_run=False)) if catalog._ghidra_installs() else None
finally:
    catalog._GHIDRA_DIR = real_dir

import zipfile
zip_path = tmp / "uv.zip"
with zipfile.ZipFile(zip_path, "w") as zf:
    for n in ("uv.exe", "uvx.exe", "uvw.exe", "README.txt"):
        zf.writestr(n, "x" * 20)
dest = tmp / "uv_dest"
placed = catalog._place_zip_exes(zip_path, tmp / "uv_scratch", dest)
results["uv_places_only_the_exes"] = placed and sorted(p.name for p in dest.iterdir()) == ["uv.exe", "uvw.exe", "uvx.exe"]
evil = tmp / "evil.zip"
with zipfile.ZipFile(evil, "w") as zf:
    zf.writestr("../escape.exe", "x")
results["zip_slip_is_refused"] = catalog._place_zip_exes(evil, tmp / "ev_scratch", tmp / "ev_dest") is False and not (tmp.parent / "escape.exe").exists()

# ---- Terminal profile refuses to run without Windows Terminal
real_target = definitions._TERMINAL_PROFILE_TARGET
try:
    definitions._TERMINAL_PROFILE_TARGET = tmp / "Packages" / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState" / "settings.json"
    ok = components["terminal_profile"].install(InstallContext(temp_dir=tmp))
    results["terminal_profile_needs_terminal_installed"] = ok is False and not (tmp / "Packages").exists()
finally:
    definitions._TERMINAL_PROFILE_TARGET = real_target

# ---- the window: optional components are never pre-checked
from ui.main_window import COL_NAME, MainWindow

app = QApplication(sys.argv)
window = MainWindow()
if window.scan_worker is not None:
    window.scan_worker.wait()
    app.processEvents()
window._save_settings = lambda: None
window._initial_scan_done = False
window._on_select_none()
for key in window.tree_items:
    window._on_component_scanned(key, InstalledState(installed=False), None)
checked = window._selected_keys()
results["first_scan_prechecks_missing_core_components"] = {"terminal", "directplay", "xna40"} <= checked
results["first_scan_never_prechecks_optional_components"] = not (checked & {k for k, c in window.component_by_key.items() if c.optional})

window._on_select_none()
window._on_select_not_installed()
checked = window._selected_keys()
results["select_needed_skips_missing_optional"] = not (checked & {"go", "rust", "chrome", "discord", "ghidra", "uv"})

window._on_component_scanned("go", InstalledState(True, "1.0.0"), LatestInfo("2.0.0", "u", "f"))
window._on_select_none()
window._on_select_not_installed()
results["select_needed_still_updates_installed_optional"] = "go" in window._selected_keys()

window.tree.setCurrentItem(window.tree_items["rust"])
details = window.details_label.text()
results["details_show_note_and_optional"] = "Visual Studio Build Tools" in details and "Optional" in details
window.tree.setCurrentItem(window.tree_items["ghidra"])
results["ghidra_details_mention_jdk"] = "JDK 21" in window.details_label.text()

window.close()
for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
