"""
The component registry — a 1:1 data-driven port of every install block in
ALLTHERUNTIMES.ps1. Each Component pairs a presence check (is_installed,
what the PS1 does inline with Test-Path/Get-ItemProperty/Get-Command) with
an installer closure (install, what the PS1 does with Get-File + Run-Exe/
Run-Msi) and an optional version resolver (resolve_latest, what the PS1
does with Get-LatestGitHubAsset/nodejs dist-index/Adoptium — surfaced here
for the GUI's "Latest Version" column, not present in the console original).

Two components (winget, and nothing else) shell out to a single PowerShell
Add-AppxPackage call — .msixbundle installation has no exe/msi equivalent
and no ergonomic ctypes/AppX-COM path, so it joins core/signature.py as the
only other PowerShell touchpoint in an otherwise pure-Python install engine.
Everything else here runs the vendor's own installer (msiexec.exe, the
downloaded .exe with its documented silent flags) or a native OS tool
(dism.exe for the NetFx3 feature) exactly as ALLTHERUNTIMES.ps1 does.
"""

import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from core import checks
from core.downloader import download
from core.installer_runner import run_exe, run_msi
from core.logger import get_logger
from core.signature import check_signature
from core.version_resolvers import LatestInfo, get_latest_adoptium, get_latest_github_asset, get_latest_node_lts

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))

ProgressCB = Optional[Callable[[str, float], None]]


@dataclass
class InstalledState:
    installed: bool
    version: Optional[str] = None


@dataclass
class InstallContext:
    temp_dir: Path
    dry_run: bool = False
    progress_cb: ProgressCB = None


@dataclass
class Component:
    key: str
    name: str
    category: str
    is_installed: Callable[[], InstalledState]
    install: Callable[[InstallContext], bool]
    resolve_latest: Optional[Callable[[], Optional[LatestInfo]]] = None


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """extractall() with a zip-slip guard. Every zip extracted here came
    from a network download — a tampered/MITM'd one could otherwise write
    outside dest_dir via a '../' entry path, since plain extractall() on
    Python versions before the 3.12 `filter="data"` option performs no such
    check at all."""
    dest_dir = dest_dir.resolve()
    for member in zf.namelist():
        target = (dest_dir / member).resolve()
        if target != dest_dir and dest_dir not in target.parents:
            raise ValueError(f"Unsafe zip entry path (would extract outside destination): {member}")
    zf.extractall(dest_dir)


# ---------------------------------------------------------------------------
# 7-ZIP PORTABLE (internal helper, not user-selectable — DirectX depends on it)
# ---------------------------------------------------------------------------

def _seven_zip_path(ctx: InstallContext) -> Path:
    return ctx.temp_dir / "7za.exe"


def ensure_seven_zip(ctx: InstallContext) -> Optional[Path]:
    """DirectX extraction needs 7za.exe. Downloaded/cached the same way the
    PS1 bootstraps it as its own pseudo-component, but folded in here since
    nothing else in the GUI's selectable list needs it standalone."""
    log = get_logger()
    exe = _seven_zip_path(ctx)
    if exe.is_file():
        return exe
    if ctx.dry_run:
        log.dry("Would download & extract 7-Zip portable (7za.exe) for DirectX extraction")
        return exe

    zip_path = download("https://www.7-zip.org/a/7za920.zip", ctx.temp_dir, "7za_bootstrap.zip", "7-Zip portable", ctx.dry_run)
    if not zip_path:
        return None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, ctx.temp_dir)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"Failed to extract 7-Zip portable: {e}")
        return None
    return exe if exe.is_file() else None


# ---------------------------------------------------------------------------
# WINGET
# ---------------------------------------------------------------------------

def _winget_is_installed() -> InstalledState:
    found = checks.command_on_path("winget")
    return InstalledState(installed=bool(found))


def _add_appx_package(path: Path) -> bool:
    log = get_logger()
    check_signature(str(path), "winget (msixbundle)")
    # See core/signature.py's matching comment: PowerShell needs a literal
    # single quote inside a single-quoted string doubled, or a path
    # containing one breaks out of the string and the install fails outright.
    escaped_path = str(path).replace("'", "''")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"Add-AppxPackage -Path '{escaped_path}'"],
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            log.status(f"Add-AppxPackage stderr: {result.stderr.strip()}")
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"Add-AppxPackage exception: {e}")
        return False


def _winget_install(ctx: InstallContext) -> bool:
    log = get_logger()
    file = download("https://aka.ms/getwinget", ctx.temp_dir, "Microsoft.DesktopAppInstaller.msixbundle", "winget", ctx.dry_run)
    if not file:
        return False
    if ctx.dry_run:
        log.dry(f"Would Add-AppxPackage {file}")
        return True

    if _add_appx_package(file):
        checks.refresh_path_env()
        return True

    log.status("Direct winget install failed; fetching dependency bundle and retrying...")
    deps_zip = download(
        "https://github.com/microsoft/winget-cli/releases/latest/download/DesktopAppInstaller_Dependencies.zip",
        ctx.temp_dir, "DesktopAppInstaller_Dependencies.zip", "winget dependencies", ctx.dry_run,
    )
    if not deps_zip:
        return False
    try:
        deps_dir = ctx.temp_dir / "winget_deps"
        with zipfile.ZipFile(deps_zip) as zf:
            _safe_extract(zf, deps_dir)
        for appx in deps_dir.rglob("*x64.appx"):
            _add_appx_package(appx)
        ok = _add_appx_package(file)
        if ok:
            checks.refresh_path_env()
        return ok
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"winget dependency retry failed: {e}")
        return False


# ---------------------------------------------------------------------------
# .NET FRAMEWORK 3.5
# ---------------------------------------------------------------------------

_NETFX3_REG = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v3.5"


def _netfx35_is_installed() -> InstalledState:
    v = checks.reg_value("HKLM", _NETFX3_REG, "Version")
    return InstalledState(installed=bool(v), version=v)


def _netfx35_install(ctx: InstallContext) -> bool:
    log = get_logger()
    if ctx.dry_run:
        log.dry("Would enable NetFx3 Windows feature via dism.exe")
        return True
    try:
        result = subprocess.run(
            ["dism.exe", "/online", "/enable-feature", "/featurename:NetFx3", "/All", "/NoRestart"],
            capture_output=True, text=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode in (0, 3010)
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"Failed: {e}")
        return False


# ---------------------------------------------------------------------------
# DIRECTX JUNE 2010
# ---------------------------------------------------------------------------

def _directx_is_installed() -> InstalledState:
    return InstalledState(installed=checks.file_exists(str(SYSTEM_ROOT / "System32" / "d3dx9_43.dll")))


def _directx_install(ctx: InstallContext) -> bool:
    log = get_logger()
    dx = download(
        "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe",
        ctx.temp_dir, "directx_Jun2010_redist.exe", "DirectX June 2010", ctx.dry_run, ctx.progress_cb,
    )
    if not dx:
        return False
    if ctx.dry_run:
        return True

    seven_zip = ensure_seven_zip(ctx)
    if not seven_zip:
        log.fail("7za.exe missing, cannot extract DirectX")
        return False

    dx_temp = ctx.temp_dir / "dx_extract"
    dx_temp.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [str(seven_zip), "x", str(dx), f"-o{dx_temp}", "-y"],
            capture_output=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"7za extraction failed: {e}")
        return False

    setup = dx_temp / "DXSETUP.exe"
    if not setup.is_file():
        log.fail("DXSETUP.exe not found in archive")
        return False
    return run_exe(setup, ["/silent"], "DirectX June 2010", ctx.dry_run)


# ---------------------------------------------------------------------------
# OPENAL (Legacy compatibility registration + OpenAL Soft runtime)
# ---------------------------------------------------------------------------
# One combo component, not two. They aren't independent: both write to the
# exact same OpenAL32.dll path, and Legacy OpenAL's only real purpose here
# is planting the HKLM\SOFTWARE\Creative Labs\OpenAL registry key that some
# old game installers check for before deciding whether to nag about/bundle
# their own OpenAL — the actual DLL that ends up loaded should always be
# Soft's modern, actively-maintained implementation. Doing them as one unit
# means "installed" can mean "both parts of that story are actually true"
# instead of two components that silently fight over the same file.

_OPENAL_DLL_PATHS = (SYSTEM_ROOT / "System32" / "OpenAL32.dll", SYSTEM_ROOT / "SysWOW64" / "OpenAL32.dll")
_OPENAL_LEGACY_REG_PATHS = [r"SOFTWARE\Creative Labs\OpenAL", r"SOFTWARE\WOW6432Node\Creative Labs\OpenAL"]


def _openal_has_legacy_key() -> bool:
    return checks.any_reg_key_exists("HKLM", _OPENAL_LEGACY_REG_PATHS)


def _openal_dll_is_soft() -> Optional[str]:
    """Returns OpenAL Soft's ProductVersion if BOTH OpenAL32.dll copies are
    verifiably its build (matched via the PE version resource, not just
    filename/existence — a same-named reference DLL from something else
    entirely, e.g. an NVIDIA driver bundle, would otherwise read as
    "installed" despite not being Soft at all). None if either isn't."""
    versions = []
    for dll_path in _OPENAL_DLL_PATHS:
        if not dll_path.is_file():
            return None
        product = checks.dll_version_field(str(dll_path), "ProductName")
        if not product or "openal soft" not in product.lower():
            return None
        versions.append(checks.dll_version_field(str(dll_path), "ProductVersion"))
    return versions[0] if versions else None


def _openal_is_installed() -> InstalledState:
    has_key = _openal_has_legacy_key()
    soft_version = _openal_dll_is_soft()
    installed = bool(has_key and soft_version)
    return InstalledState(installed=installed, version=soft_version if installed else None)


def _openal_install_legacy_step(ctx: InstallContext) -> bool:
    log = get_logger()
    zip_path = download("https://openal.org/downloads/oalinst.zip", ctx.temp_dir, "oalinst.zip", "OpenAL (Legacy compat)", ctx.dry_run)
    if not zip_path:
        return False
    if ctx.dry_run:
        log.dry("Would plant HKLM\\SOFTWARE\\Creative Labs\\OpenAL compatibility registry key")
        return True
    extract_dir = ctx.temp_dir / "oal_legacy"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, extract_dir)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"Extraction failed: {e}")
        return False
    exe = extract_dir / "oalinst.exe"
    if exe.is_file():
        # Best-effort: on a genuinely bare machine (no pre-existing
        # OpenAL32.dll of any kind) this may do a real, fuller install.
        # Its own exit code isn't trusted as the final word, though — see
        # the marker-key write below.
        run_exe(exe, ["/S"], "OpenAL (Legacy compat)", ctx.dry_run)

    if checks.reg_key_exists("HKLM", _OPENAL_LEGACY_REG_PATHS[0]):
        return True

    # oalinst.exe's silent mode can't be trusted to actually register
    # anything on modern Windows — confirmed on a real machine: it exited 0
    # but wrote nothing to the registry at all (native, WOW6432Node, HKCU,
    # or even UAC's VirtualStore redirect), apparently because it does its
    # own internal version check against whatever OpenAL32.dll is already
    # present and silently no-ops if that looks newer than what it ships.
    # The key's only real job is being present for old installers that
    # check for it, so guarantee it directly rather than depend on that.
    if checks.create_reg_marker_key("HKLM", _OPENAL_LEGACY_REG_PATHS[0], {
        "InstalledBy": "AIO Runtime Installer (OpenAL Soft runtime underneath)",
    }):
        return True

    log.fail("Could not create OpenAL compatibility registry key")
    return False


def _openal_install_soft_step(ctx: InstallContext) -> bool:
    log = get_logger()
    zip_path = download(
        "https://openal-soft.org/openal-binaries/openal-soft-1.25.1-bin.zip",
        ctx.temp_dir, "openal-soft-latest-bin.zip", "OpenAL (Soft runtime)", ctx.dry_run,
    )
    if not zip_path:
        return False
    if ctx.dry_run:
        return True
    extract_dir = ctx.temp_dir / "oal_soft"
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, extract_dir)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"Extraction failed: {e}")
        return False

    dll64 = next((p for p in extract_dir.rglob("soft_oal.dll") if "Win64" in p.parts), None)
    dll32 = next((p for p in extract_dir.rglob("soft_oal.dll") if "Win32" in p.parts), None)
    if not (dll64 and dll32):
        log.fail("soft_oal.dll not found in expected paths")
        return False

    dest64, dest32 = _OPENAL_DLL_PATHS
    try:
        shutil.copyfile(dll64, dest64)
        shutil.copyfile(dll32, dest32)
        return True
    except OSError as e:
        log.fail(f"Copy failed: {e}")
        return False


def _openal_install(ctx: InstallContext) -> bool:
    """Runs only whichever half is actually missing — e.g. a machine that
    already has a working Soft DLL from a previous run just gets the
    registry key planted, not a redundant re-download+copy."""
    if not _openal_has_legacy_key():
        if not _openal_install_legacy_step(ctx):
            return False
    if not _openal_dll_is_soft():
        if not _openal_install_soft_step(ctx):
            return False
    return True


# ---------------------------------------------------------------------------
# VISUAL C++ REDISTRIBUTABLES
# ---------------------------------------------------------------------------

@dataclass
class _VCDef:
    key: str
    base: str
    flags: List[str]
    url: str
    uninstall_pattern: Optional["re.Pattern[str]"] = None


_VC_DEFS = [
    # 2005/2008 predate the MSI "provider key" dependency-tracking mechanism
    # (2012+ era) and never register under Installer\Dependencies — they
    # only ever show up in the classic Uninstall (Programs and Features)
    # key, and with an inconsistent naming scheme per year: 2005's x86
    # package omits the arch tag entirely, 2008 uses " - x86"/" - x64"
    # rather than the "(x86)"/"(x64)" suffix later years use. Confirmed
    # against a real machine with both years actually installed.
    _VCDef("2005_x86", "8.0", ["/q:a"], "https://download.microsoft.com/download/8/B/4/8B42259F-5D70-43F4-AC2E-4B208FD8D66A/vcredist_x86.exe",
           uninstall_pattern=re.compile(r"^Microsoft Visual C\+\+ 2005 Redistributable$", re.IGNORECASE)),
    _VCDef("2005_x64", "8.0", ["/q:a"], "https://download.microsoft.com/download/8/B/4/8B42259F-5D70-43F4-AC2E-4B208FD8D66A/vcredist_x64.exe",
           uninstall_pattern=re.compile(r"Visual C\+\+ 2005 Redistributable \(x64\)", re.IGNORECASE)),
    _VCDef("2008_x86", "9.0", ["/q"], "https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x86.exe",
           uninstall_pattern=re.compile(r"Visual C\+\+ 2008 Redistributable - x86", re.IGNORECASE)),
    _VCDef("2008_x64", "9.0", ["/q"], "https://download.microsoft.com/download/5/D/8/5D8C65CB-C849-4025-8E95-C3966CAFD8AE/vcredist_x64.exe",
           uninstall_pattern=re.compile(r"Visual C\+\+ 2008 Redistributable - x64", re.IGNORECASE)),
    _VCDef("2010_x86", "10.0", ["/q"], "https://catalog.s.download.windowsupdate.com/msdownload/update/software/secu/2011/07/vcredist_x86_28c54491be70c38c97849c3d8cfbfdd0d3c515cb.exe"),
    _VCDef("2010_x64", "10.0", ["/q"], "https://catalog.s.download.windowsupdate.com/msdownload/update/software/secu/2011/07/vcredist_x64_15d032d669078aa6f0f7fd1cbf4115a070bd034d.exe"),
    _VCDef("2012_x86", "11.0", ["/passive", "/norestart"], "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/vcredist_x86.exe"),
    _VCDef("2012_x64", "11.0", ["/passive", "/norestart"], "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/vcredist_x64.exe"),
    _VCDef("2013_x86", "12.0", ["/passive", "/norestart"], "https://download.microsoft.com/download/2/E/6/2E61CFA4-993B-4DD4-91DA-3737CD5CD6E3/vcredist_x86.exe"),
    _VCDef("2013_x64", "12.0", ["/passive", "/norestart"], "https://download.microsoft.com/download/2/E/6/2E61CFA4-993B-4DD4-91DA-3737CD5CD6E3/vcredist_x64.exe"),
    _VCDef("2015-2022_x86", "14.0", ["/quiet", "/norestart"], "https://aka.ms/vs/17/release/vc_redist.x86.exe"),
    _VCDef("2015-2022_x64", "14.0", ["/quiet", "/norestart"], "https://aka.ms/vs/17/release/vc_redist.x64.exe"),
]


def _vc_is_installed(vc: _VCDef) -> InstalledState:
    arch = vc.key.rsplit("_", 1)[-1]
    for hive_root in (
        rf"SOFTWARE\Microsoft\VisualStudio\{vc.base}\VC\VCRedist\{arch}",
        rf"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\{vc.base}\VC\VCRedist\{arch}",
    ):
        v = checks.reg_value("HKLM", hive_root, "Version")
        if v:
            return InstalledState(installed=True, version=v)

    if vc.uninstall_pattern is not None:
        # 2005/2008: only ever registered in the classic Uninstall key.
        version = checks.find_uninstall_entry_by_display_name(vc.uninstall_pattern)
        if version:
            return InstalledState(installed=True, version=version)
    else:
        # 2010+: newer VC++ installers (14.30+) don't always populate the
        # classic VCRedist key above but do register under
        # Installer\Dependencies (confirmed on a real machine: 2012/2013/
        # 2015-2022 were all actually installed and invisible to the check
        # above, present here as expected).
        year_label = vc.key.rsplit("_", 1)[0]
        pattern = re.compile(rf"Visual C\+\+ {re.escape(year_label)}.*\({re.escape(arch)}\)", re.IGNORECASE)
        version = checks.find_dependency_by_display_name(pattern)
        if version:
            return InstalledState(installed=True, version=version)

    return InstalledState(installed=False)


def _vc_install(vc: _VCDef, ctx: InstallContext) -> bool:
    file = download(vc.url, ctx.temp_dir, f"vc_{vc.key}.exe", f"VC++ {vc.key}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, vc.flags, f"VC++ {vc.key}", ctx.dry_run)


# ---------------------------------------------------------------------------
# .NET RUNTIMES
# ---------------------------------------------------------------------------

@dataclass
class _NetDef:
    name: str
    file: str
    flags: List[str]
    is_framework: bool
    reg: str
    url: str
    ver: Optional[str] = None
    min_release: Optional[int] = None
    shared_fx: Optional[str] = None


_DOTNET_SHARED_ROOT = PROGRAM_FILES / "dotnet" / "shared"

_NET_DEFS = [
    _NetDef(".NET Framework 4.8.1", "ndp481.exe", ["/q", "/norestart"], True,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
            "https://go.microsoft.com/fwlink/?linkid=2202440", min_release=528040),
    _NetDef(".NET 8 ASP.NET Core Runtime", "aspnetcore-8.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.AspNetCore.App",
            "https://aka.ms/dotnet/8.0/aspnetcore-runtime-win-x64.exe", ver="8.0", shared_fx="Microsoft.AspNetCore.App"),
    _NetDef(".NET 8 Desktop Runtime", "desktop-8.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App",
            "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe", ver="8.0", shared_fx="Microsoft.WindowsDesktop.App"),
    _NetDef(".NET 9 ASP.NET Core Runtime", "aspnetcore-9.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.AspNetCore.App",
            "https://aka.ms/dotnet/9.0/aspnetcore-runtime-win-x64.exe", ver="9.0", shared_fx="Microsoft.AspNetCore.App"),
    _NetDef(".NET 9 Desktop Runtime", "desktop-9.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App",
            "https://aka.ms/dotnet/9.0/windowsdesktop-runtime-win-x64.exe", ver="9.0", shared_fx="Microsoft.WindowsDesktop.App"),
    _NetDef(".NET 10 ASP.NET Core Runtime", "aspnetcore-10.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.AspNetCore.App",
            "https://aka.ms/dotnet/10.0/aspnetcore-runtime-win-x64.exe", ver="10.0", shared_fx="Microsoft.AspNetCore.App"),
    _NetDef(".NET 10 Desktop Runtime", "desktop-10.exe", ["/quiet", "/norestart"], False,
            r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.WindowsDesktop.App",
            "https://aka.ms/dotnet/10.0/windowsdesktop-runtime-win-x64.exe", ver="10.0", shared_fx="Microsoft.WindowsDesktop.App"),
]


def _net_is_installed(nd: _NetDef) -> InstalledState:
    if nd.is_framework:
        rel = checks.reg_value_int("HKLM", nd.reg, "Release")
        installed = bool(rel and nd.min_release and rel >= nd.min_release)
        return InstalledState(installed=installed, version=str(rel) if rel else None)

    # The registry key (HKLM\SOFTWARE\dotnet\Setup\InstalledVersions\...) is
    # only reliably populated by the classic MSI installer. Runtimes placed
    # by winget or the dotnet-install script leave it empty despite being
    # fully installed and visible to `dotnet --list-runtimes` — confirmed on
    # a real machine (8/9/10 all present on disk, registry key absent). The
    # shared framework folder is the ground truth `dotnet` itself reads from.
    match = checks.any_child_dir_matches(str(_DOTNET_SHARED_ROOT / nd.shared_fx), f"{nd.ver}.")
    if match:
        return InstalledState(installed=True, version=match.name)

    installed = checks.reg_key_exists("HKLM", f"{nd.reg}\\{nd.ver}")
    return InstalledState(installed=installed, version=nd.ver if installed else None)


def _net_install(nd: _NetDef, ctx: InstallContext) -> bool:
    file = download(nd.url, ctx.temp_dir, nd.file, nd.name, ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, nd.flags, nd.name, ctx.dry_run)


# ---------------------------------------------------------------------------
# TEMURIN JDK
# ---------------------------------------------------------------------------

@dataclass
class _JdkDef:
    name: str
    feature_version: int
    dir_prefix: str
    fallback_version: str


_JDK_DEFS = [
    _JdkDef("Temurin JDK 21", 21, "jdk-21", "21.0.4"),
    _JdkDef("Temurin JDK 17", 17, "jdk-17", "17.0.12"),
    _JdkDef("Temurin JDK 8", 8, "jdk-8", "8.0.422"),
]

_ADOPTIUM_ROOT = PROGRAM_FILES / "Eclipse Adoptium"


def _jdk_is_installed(jd: _JdkDef) -> InstalledState:
    match = checks.any_child_dir_matches(str(_ADOPTIUM_ROOT), jd.dir_prefix)
    return InstalledState(installed=bool(match), version=match.name if match else None)


def _jdk_resolve_latest(jd: _JdkDef) -> Optional[LatestInfo]:
    return get_latest_adoptium(jd.feature_version, jd.fallback_version)


def _jdk_install(jd: _JdkDef, ctx: InstallContext) -> bool:
    latest = _jdk_resolve_latest(jd)
    file = download(latest.url, ctx.temp_dir, f"temurin-jdk-{jd.feature_version}.msi", jd.name, ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_msi(file, ["/quiet", "/norestart", "INSTALLLEVEL=1"], jd.name, ctx.dry_run)


# ---------------------------------------------------------------------------
# VULKAN RUNTIME
# ---------------------------------------------------------------------------

def _vulkan_is_installed() -> InstalledState:
    # The Runtime registry key isn't always written (confirmed on a real
    # machine: absent despite vulkan-1.dll being present and the runtime
    # fully usable) — vulkan-1.dll in System32 is the loader every Vulkan
    # app actually depends on, so its presence is the more reliable signal.
    has_reg = checks.reg_key_exists("HKLM", r"SOFTWARE\Khronos\Vulkan\Runtime")
    has_dll = checks.file_exists(str(SYSTEM_ROOT / "System32" / "vulkan-1.dll"))
    return InstalledState(installed=has_reg or has_dll)


def _vulkan_install(ctx: InstallContext) -> bool:
    file = download("https://sdk.lunarg.com/sdk/download/latest/windows/vulkan-runtime.exe", ctx.temp_dir, "vulkan-runtime.exe", "Vulkan Runtime", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, ["/S"], "Vulkan Runtime", ctx.dry_run)


# ---------------------------------------------------------------------------
# WEBVIEW2
# ---------------------------------------------------------------------------

_WEBVIEW2_CLIENT_ID = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_is_installed() -> InstalledState:
    # The per-machine WebView2 Evergreen Runtime commonly registers its
    # Clients key under WOW6432Node even on a 64-bit OS (confirmed on a real
    # machine: absent from the plain HKLM path, present under WOW6432Node) —
    # same pattern as the Chromium-based updater family in general.
    installed = checks.any_reg_key_exists("HKLM", [
        rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}",
    ])
    return InstalledState(installed=installed)


def _webview2_install(ctx: InstallContext) -> bool:
    file = download("https://go.microsoft.com/fwlink/p/?LinkId=2124703", ctx.temp_dir, "MicrosoftEdgeWebview2Setup.exe", "WebView2", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, ["/silent", "/install"], "WebView2", ctx.dry_run)


# ---------------------------------------------------------------------------
# POWERSHELL 7
# ---------------------------------------------------------------------------

_PWSH_PATTERN = re.compile(r"^PowerShell-[\d.]+-win-x64\.msi$")
_PWSH_FALLBACK_URL = "https://github.com/PowerShell/PowerShell/releases/download/v7.6.1/PowerShell-7.6.1-win-x64.msi"
_PWSH_FALLBACK_VERSION = "7.6.1"
_PWSH_EXE = PROGRAM_FILES / "PowerShell" / "7" / "pwsh.exe"


def _pwsh_resolve_latest() -> LatestInfo:
    return get_latest_github_asset("PowerShell/PowerShell", _PWSH_PATTERN, _PWSH_FALLBACK_URL, _PWSH_FALLBACK_VERSION)


def _pwsh_is_installed() -> InstalledState:
    if not _PWSH_EXE.is_file():
        return InstalledState(installed=False)
    out = checks.command_version(str(_PWSH_EXE), ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"])
    return InstalledState(installed=bool(out), version=out)


def _pwsh_install(ctx: InstallContext) -> bool:
    latest = _pwsh_resolve_latest()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"PowerShell {latest.version}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_msi(
        file,
        ["/quiet", "/norestart", "ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=1",
         "ADD_FILE_CONTEXT_MENU_RUNPOWERSHELL=1", "ENABLE_PSREMOTING=1", "REGISTER_MANIFEST=1", "ADD_PATH=1"],
        f"PowerShell {latest.version}", ctx.dry_run,
    )


# ---------------------------------------------------------------------------
# PYTHON (pinned versions)
# ---------------------------------------------------------------------------

@dataclass
class _PyDef:
    ver: str
    url: str


_PY_DEFS = [
    _PyDef("3.10", "https://www.python.org/ftp/python/3.10.20/python-3.10.20-amd64.exe"),
    _PyDef("3.11", "https://www.python.org/ftp/python/3.11.15/python-3.11.15-amd64.exe"),
    _PyDef("3.12", "https://www.python.org/ftp/python/3.12.13/python-3.12.13-amd64.exe"),
    _PyDef("3.13", "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe"),
]


def _py_dir(py: _PyDef) -> Path:
    return PROGRAM_FILES / f"Python{py.ver.replace('.', '')}"


def _py_is_installed(py: _PyDef) -> InstalledState:
    installed = checks.file_exists(str(_py_dir(py) / "python.exe"))
    return InstalledState(installed=installed, version=py.ver if installed else None)


def _py_install(py: _PyDef, ctx: InstallContext) -> bool:
    file = download(py.url, ctx.temp_dir, f"python-{py.ver}-amd64.exe", f"Python {py.ver}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, ["/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_launcher=1"], f"Python {py.ver}", ctx.dry_run)


# ---------------------------------------------------------------------------
# GIT FOR WINDOWS
# ---------------------------------------------------------------------------

_GIT_PATTERN = re.compile(r"^Git-[\d.]+-64-bit\.exe$")
_GIT_FALLBACK_URL = "https://github.com/git-for-windows/git/releases/download/v2.54.0.windows.1/Git-2.54.0-64-bit.exe"
_GIT_FALLBACK_VERSION = "2.54.0"
_GIT_EXE = PROGRAM_FILES / "Git" / "bin" / "git.exe"


def _git_resolve_latest() -> LatestInfo:
    return get_latest_github_asset("git-for-windows/git", _GIT_PATTERN, _GIT_FALLBACK_URL, _GIT_FALLBACK_VERSION)


def _git_is_installed() -> InstalledState:
    if not _GIT_EXE.is_file():
        return InstalledState(installed=False)
    out = checks.command_version(str(_GIT_EXE), ["--version"])
    version = out.removeprefix("git version ").strip() if out else None
    return InstalledState(installed=True, version=version)


def _git_install(ctx: InstallContext) -> bool:
    latest = _git_resolve_latest()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"Git {latest.version}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(
        file,
        ["/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/COMPONENTS=icons,assoc,assoc_sh,gitlfs"],
        f"Git {latest.version}", ctx.dry_run,
    )


# ---------------------------------------------------------------------------
# NODE.JS (latest LTS)
# ---------------------------------------------------------------------------

_NODE_FALLBACK_VERSION = "24.18.1"
_NODE_FALLBACK_URL = "https://nodejs.org/dist/v24.18.1/node-v24.18.1-x64.msi"
_NODE_EXE = PROGRAM_FILES / "nodejs" / "node.exe"


def _node_resolve_latest() -> LatestInfo:
    return get_latest_node_lts(_NODE_FALLBACK_VERSION, _NODE_FALLBACK_URL)


def _node_is_installed() -> InstalledState:
    if not _NODE_EXE.is_file():
        return InstalledState(installed=False)
    out = checks.command_version(str(_NODE_EXE), ["--version"])
    version = out.lstrip("v").strip() if out else None
    return InstalledState(installed=True, version=version)


def _node_install(ctx: InstallContext) -> bool:
    latest = _node_resolve_latest()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"Node.js {latest.version}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_msi(file, ["/quiet", "/norestart", "ADDLOCAL=ALL"], f"Node.js {latest.version}", ctx.dry_run)


# ---------------------------------------------------------------------------
# CMAKE
# ---------------------------------------------------------------------------

_CMAKE_PATTERN = re.compile(r"^cmake-[\d.]+-windows-x86_64\.msi$")
_CMAKE_FALLBACK_URL = "https://github.com/Kitware/CMake/releases/download/v4.4.1/cmake-4.4.1-windows-x86_64.msi"
_CMAKE_FALLBACK_VERSION = "4.4.1"
_CMAKE_EXE = PROGRAM_FILES / "CMake" / "bin" / "cmake.exe"


def _cmake_resolve_latest() -> LatestInfo:
    return get_latest_github_asset("Kitware/CMake", _CMAKE_PATTERN, _CMAKE_FALLBACK_URL, _CMAKE_FALLBACK_VERSION)


def _cmake_is_installed() -> InstalledState:
    if not _CMAKE_EXE.is_file():
        return InstalledState(installed=False)
    out = checks.command_version(str(_CMAKE_EXE), ["--version"])
    first_line = out.splitlines()[0] if out else ""
    version = first_line.removeprefix("cmake version ").strip() or None
    return InstalledState(installed=True, version=version)


def _cmake_install(ctx: InstallContext) -> bool:
    latest = _cmake_resolve_latest()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"CMake {latest.version}", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_msi(file, ["/quiet", "/norestart", "ADD_CMAKE_TO_PATH=System"], f"CMake {latest.version}", ctx.dry_run)


# ---------------------------------------------------------------------------
# VS CODE
# ---------------------------------------------------------------------------

_VSCODE_EXE = LOCAL_APPDATA / "Programs" / "Microsoft VS Code" / "Code.exe"


def _vscode_is_installed() -> InstalledState:
    return InstalledState(installed=checks.file_exists(str(_VSCODE_EXE)))


def _vscode_install(ctx: InstallContext) -> bool:
    file = download("https://aka.ms/win32-x64-user-stable", ctx.temp_dir, "VSCodeSetup-x64.exe", "VS Code", ctx.dry_run, ctx.progress_cb)
    if not file:
        return False
    return run_exe(file, ["/VERYSILENT", "/NORESTART", "/MERGETASKS=!runcode"], "VS Code", ctx.dry_run)


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------

def build_components() -> List[Component]:
    components: List[Component] = [
        Component("winget", "winget (Windows Package Manager)", "Core Runtimes", _winget_is_installed, _winget_install),
        Component("netfx35", ".NET Framework 3.5", "Core Runtimes", _netfx35_is_installed, _netfx35_install),
        Component("directx", "DirectX June 2010 (legacy DirectX 9.0c)", "Core Runtimes", _directx_is_installed, _directx_install),
        Component("openal", "OpenAL (Legacy compat + Soft runtime)", "Core Runtimes", _openal_is_installed, _openal_install),
        Component("vulkan", "Vulkan Runtime", "Core Runtimes", _vulkan_is_installed, _vulkan_install),
        Component("webview2", "Microsoft Edge WebView2 Runtime", "Core Runtimes", _webview2_is_installed, _webview2_install),
    ]

    for vc in _VC_DEFS:
        components.append(Component(
            f"vc_{vc.key}", f"VC++ Redistributable {vc.key}", "VC++ Redistributables",
            lambda vc=vc: _vc_is_installed(vc),
            lambda ctx, vc=vc: _vc_install(vc, ctx),
        ))

    for nd in _NET_DEFS:
        components.append(Component(
            f"net_{nd.name}", nd.name, ".NET Runtimes",
            lambda nd=nd: _net_is_installed(nd),
            lambda ctx, nd=nd: _net_install(nd, ctx),
        ))

    for jd in _JDK_DEFS:
        components.append(Component(
            f"jdk_{jd.feature_version}", jd.name, "Java (Temurin JDK)",
            lambda jd=jd: _jdk_is_installed(jd),
            lambda ctx, jd=jd: _jdk_install(jd, ctx),
            lambda jd=jd: _jdk_resolve_latest(jd),
        ))

    for py in _PY_DEFS:
        components.append(Component(
            f"python_{py.ver}", f"Python {py.ver}", "Python",
            lambda py=py: _py_is_installed(py),
            lambda ctx, py=py: _py_install(py, ctx),
        ))

    components += [
        Component("pwsh", "PowerShell 7", "Dev Tools", _pwsh_is_installed, _pwsh_install, _pwsh_resolve_latest),
        Component("git", "Git for Windows", "Dev Tools", _git_is_installed, _git_install, _git_resolve_latest),
        Component("node", "Node.js (LTS)", "Dev Tools", _node_is_installed, _node_install, _node_resolve_latest),
        Component("cmake", "CMake", "Dev Tools", _cmake_is_installed, _cmake_install, _cmake_resolve_latest),
        Component("vscode", "Visual Studio Code", "Dev Tools", _vscode_is_installed, _vscode_install),
    ]

    return components
