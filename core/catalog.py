"""
Extra components, kept apart from definitions.py's core registry:

  Windows Terminal           Dev Tools            (verified msixbundle from GitHub)
  DirectPlay, XNA 4.0, PhysX Legacy Game Support
  uv                         Python               (portable zip)
  Go, Rust                   Go & Rust
  MSYS2, Inno Setup, Ghidra  Dev Tools
  Chrome, Discord, AnyDesk, Claude   Apps

Two install styles live here:

  * our own pipeline (download -> hash / Authenticode check -> run), same as
    the core registry, for things with stable URLs and known silent flags
    (Terminal, Chrome, XNA, Go, Rust, uv, Ghidra);
  * `winget` as the installer for packages whose silent-install switches are
    fiddly and already maintained by the winget community (Discord, AnyDesk,
    Claude, MSYS2, Inno Setup, PhysX). winget verifies each installer against
    the hash in its reviewed manifest. These need the "winget" component.

Anything marked `optional` is never pre-checked by a scan or "Select needed".
"""

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from core import checks, http_cache, path_backup
from core.definitions import (
    LOCAL_APPDATA, MICROSOFT, PROGRAM_FILES, SYSTEM_ROOT, Component, InstalledState, InstallContext,
    _add_appx_package, _generic_registry_uninstall, _run_uninstall_command, _safe_extract,
)
from core.downloader import Trust, download
from core.installer_runner import run_exe, run_msi
from core.logger import get_logger
from core.version_resolvers import LatestInfo, asset_sha256, github_headers

PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
_NO_WINDOW = subprocess.CREATE_NO_WINDOW
_UA = {"User-Agent": "Runtime-Forge"}


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _github_latest(repo: str, pattern: "re.Pattern[str]", tag_to_version: Callable[[str], str],
                   fallback: Optional[LatestInfo] = None) -> LatestInfo:
    """Latest release of `repo`: the asset matching `pattern`, its GitHub-published
    SHA-256, and a version derived from the tag. Falls back to `fallback` (a
    pinned release) when the API can't be read, or raises if there isn't one."""
    log = get_logger()
    try:
        resp = http_cache.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=github_headers(), timeout=15)
        resp.raise_for_status()
        release = resp.json()
        for asset in release.get("assets", []):
            if pattern.search(asset["name"]):
                return LatestInfo(
                    version=tag_to_version(release["tag_name"]), url=asset["browser_download_url"],
                    filename=asset["name"], sha256=asset_sha256(asset),
                )
        raise LookupError(f"{repo}'s latest release has no asset matching {pattern.pattern}")
    except Exception as e:  # noqa: BLE001 - any failure -> pinned fallback or a clear error
        if fallback is not None:
            log.status(f"Could not query GitHub for {repo} ({e}); using pinned fallback")
            return fallback
        raise


def _command_version(exe: Path, args: List[str], pattern: str) -> Optional[str]:
    out = checks.command_version(str(exe), args)
    match = re.search(pattern, out or "")
    return match.group(1) if match else None


def _place_zip_exes(zip_path: Path, scratch: Path, install_dir: Path) -> bool:
    """Extract `zip_path` and copy its top-level .exe files into `install_dir`."""
    log = get_logger()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, scratch)
        install_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for exe in scratch.glob("*.exe"):
            shutil.copyfile(exe, install_dir / exe.name)
            copied += 1
        if not copied:
            log.fail(f"No .exe files found in {zip_path.name}")
            return False
        return True
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"Could not place files in {install_dir}: {e}")
        return False


def _extract_zip_tree(zip_path: Path, dest: Path) -> bool:
    """Extract `zip_path` (which carries its own top-level folder) into `dest`."""
    log = get_logger()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, dest)
        return True
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        log.fail(f"Could not extract {zip_path.name} into {dest}: {e}")
        return False


def _remove_tree(path: Path, name: str, ctx: InstallContext) -> bool:
    log = get_logger()
    if ctx.dry_run:
        log.dry(f"Would delete {path}")
        return True
    try:
        shutil.rmtree(path)
        log.success(f"{name} removed ({path})")
        return True
    except OSError as e:
        log.fail(f"Could not remove {path}: {e}")
        return False


# ---------------------------------------------------------------------------
# winget-backed components
# ---------------------------------------------------------------------------

_WINGET_BASE = ["--accept-source-agreements", "--disable-interactivity"]


def _winget_exe() -> Optional[str]:
    return checks.command_on_path("winget")


def _winget_run(args: List[str], name: str, ctx: InstallContext, timeout: int = 1800) -> bool:
    log = get_logger()
    if ctx.dry_run:
        log.dry(f"Would run: winget {' '.join(args)}")
        return True
    exe = _winget_exe()
    if not exe:
        log.fail("winget isn't installed - install the 'winget' component first")
        return False
    log.status(f"Running: winget {' '.join(args)}")
    try:
        result = subprocess.run(
            [exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"winget failed to run: {e}")
        return False
    tail = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip() and not set(ln.strip()) <= set("-\\|/ ")]
    for line in tail[-4:]:
        log.status(f"       winget: {line}")
    log.status(f"       Exit code: {result.returncode}")
    return result.returncode == 0


def _winget_component(key: str, name: str, category: str, winget_id: str,
                      is_installed: Callable[[], InstalledState], note: str = "",
                      optional: bool = True, location: Optional[Callable[[], Optional[Path]]] = None) -> Component:
    def install(ctx: InstallContext) -> bool:
        return _winget_run(
            ["install", "--id", winget_id, "-e", "--silent", "--accept-package-agreements", *_WINGET_BASE],
            name, ctx,
        )

    def uninstall(ctx: InstallContext) -> bool:
        return _winget_run(["uninstall", "--id", winget_id, "-e", "--silent", *_WINGET_BASE], name, ctx, timeout=900)

    return Component(
        key, name, category, is_installed, install, uninstall=uninstall, optional=optional,
        note=(note + " " if note else "") + f"Installed with winget ({winget_id}), which checks the installer against its reviewed manifest hash.",
        location=location,
    )


def _entry_state(pattern: str) -> InstalledState:
    """Installed state from a Programs-and-Features entry (HKLM or HKCU)."""
    found = checks.find_uninstall_entry_by_display_name(re.compile(pattern, re.IGNORECASE))
    if not found:
        return InstalledState(installed=False)
    version = re.search(r"\d[\w.\-+]*", found)
    return InstalledState(installed=True, version=version.group(0) if version else None)


def _discord_state() -> InstalledState:
    state = _entry_state(r"^Discord$")
    if state.installed:
        return state
    base = LOCAL_APPDATA / "Discord"
    versions = sorted(base.glob("app-*"), reverse=True) if base.is_dir() else []
    if (base / "Update.exe").is_file() and versions:
        return InstalledState(installed=True, version=versions[0].name.removeprefix("app-"))
    return InstalledState(installed=False)


def _anydesk_state() -> InstalledState:
    for base in (PROGRAM_FILES_X86, PROGRAM_FILES):
        exe = base / "AnyDesk" / "AnyDesk.exe"
        if exe.is_file():
            state = _entry_state(r"^AnyDesk$")  # its DisplayVersion reads like "ad 9.7.3"
            return InstalledState(True, state.version or checks.dll_version_field(str(exe), "ProductVersion"))
    return InstalledState(installed=False)


def _claude_state() -> InstalledState:
    version = checks.appx_package_version("Claude", "pzs8sxrjxfjjc")
    if version:
        return InstalledState(True, version)
    return _entry_state(r"^Claude$")


def _msys2_state() -> InstalledState:
    if not (Path(r"C:\msys64") / "msys2_shell.cmd").is_file():
        return InstalledState(installed=False)
    return InstalledState(True, _entry_state(r"^MSYS2").version)


def _msys2_location() -> Optional[Path]:
    return Path(r"C:\msys64")


def _inno_state() -> InstalledState:
    state = _entry_state(r"^Inno Setup")
    if state.installed:
        return state
    for base in (PROGRAM_FILES_X86, PROGRAM_FILES, LOCAL_APPDATA / "Programs"):
        for iscc in sorted(base.glob("Inno Setup */ISCC.exe"), reverse=True) if base.is_dir() else []:
            return InstalledState(True, checks.dll_version_field(str(iscc), "ProductVersion"))
    return InstalledState(installed=False)


def _physx_state() -> InstalledState:
    return _entry_state(r"^NVIDIA PhysX System Software")


# ---------------------------------------------------------------------------
# Windows Terminal (msixbundle, our own verified pipeline)
# ---------------------------------------------------------------------------

_TERMINAL_PATTERN = re.compile(r"^Microsoft\.WindowsTerminal_[\d.]+_8wekyb3d8bbwe\.msixbundle$")
_TERMINAL_FALLBACK = LatestInfo(
    "1.25.2733.0",
    "https://github.com/microsoft/terminal/releases/download/v1.25.2733.0/Microsoft.WindowsTerminal_1.25.2733.0_8wekyb3d8bbwe.msixbundle",
    "Microsoft.WindowsTerminal_1.25.2733.0_8wekyb3d8bbwe.msixbundle",
    "cce6e9cc3c8457fa11ced1d2a7354888c7d6db83c5ace5d5891a52c95e3b21da",
)


def _terminal_resolve() -> LatestInfo:
    return _github_latest("microsoft/terminal", _TERMINAL_PATTERN, lambda tag: tag.lstrip("v"), _TERMINAL_FALLBACK)


def _terminal_state() -> InstalledState:
    version = checks.appx_package_version("Microsoft.WindowsTerminal", "8wekyb3d8bbwe")
    return InstalledState(installed=bool(version), version=version)


def _terminal_install(ctx: InstallContext) -> bool:
    log = get_logger()
    latest = _terminal_resolve()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"Windows Terminal {latest.version}", ctx.dry_run,
                    ctx.progress_cb, trust=Trust(publishers=MICROSOFT, sha256=latest.sha256))
    if not file:
        return False
    if ctx.dry_run:
        log.dry(f"Would Add-AppxPackage {file}")
        return True
    return _add_appx_package(file)


# ---------------------------------------------------------------------------
# Legacy game support: DirectPlay, XNA 4.0, PhysX
# ---------------------------------------------------------------------------

def _directplay_state() -> InstalledState:
    dlls = (SYSTEM_ROOT / "System32" / "dplayx.dll", SYSTEM_ROOT / "SysWOW64" / "dplayx.dll")
    if not all(dll.is_file() for dll in dlls):
        return InstalledState(installed=False)
    return InstalledState(True, checks.dll_version_field(str(dlls[0]), "ProductVersion"))


def _dism_feature(feature: str, enable: bool, ctx: InstallContext) -> bool:
    log = get_logger()
    verb = "enable" if enable else "disable"
    args = ["dism.exe", "/online", f"/{verb}-feature", f"/featurename:{feature}", "/NoRestart"]
    if enable:
        args.insert(4, "/All")
    if ctx.dry_run:
        log.dry(f"Would {verb} the {feature} Windows feature via dism.exe")
        return True
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=600, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"dism failed: {e}")
        return False
    log.status(f"       Exit code: {result.returncode}")
    return result.returncode in (0, 3010)


_XNA_URL = "https://download.microsoft.com/download/A/C/2/AC2C903B-E6E8-42C2-9FD7-BEBAC362A930/xnafx40_redist.msi"
_XNA_PATTERN = r"XNA Framework Redistributable 4\.0"


def _xna_install(ctx: InstallContext) -> bool:
    file = download(_XNA_URL, ctx.temp_dir, "xnafx40_redist.msi", "XNA Framework 4.0", ctx.dry_run, ctx.progress_cb,
                    trust=Trust(publishers=MICROSOFT))
    if not file:
        return False
    return run_msi(file, ["/qn", "/norestart"], "XNA Framework 4.0", ctx.dry_run)


# ---------------------------------------------------------------------------
# Chrome (MSI, self-updating - so no "latest version" to compare against)
# ---------------------------------------------------------------------------

_CHROME_URL = "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"


def _chrome_exe() -> Optional[Path]:
    for base in (PROGRAM_FILES, PROGRAM_FILES_X86):
        exe = base / "Google" / "Chrome" / "Application" / "chrome.exe"
        if exe.is_file():
            return exe
    return None


def _chrome_state() -> InstalledState:
    exe = _chrome_exe()
    if exe is None:
        return InstalledState(installed=False)
    return InstalledState(True, checks.dll_version_field(str(exe), "ProductVersion"))


def _chrome_install(ctx: InstallContext) -> bool:
    file = download(_CHROME_URL, ctx.temp_dir, "googlechromestandaloneenterprise64.msi", "Google Chrome", ctx.dry_run,
                    ctx.progress_cb, trust=Trust(publishers=("Google",)))
    if not file:
        return False
    return run_msi(file, ["/qn", "/norestart"], "Google Chrome", ctx.dry_run)


# ---------------------------------------------------------------------------
# Go (MSI; the download page's JSON carries each file's SHA-256)
# ---------------------------------------------------------------------------

_GO_EXE = PROGRAM_FILES / "Go" / "bin" / "go.exe"


def _go_resolve() -> LatestInfo:
    resp = http_cache.get("https://go.dev/dl/?mode=json", headers=_UA, timeout=15)
    resp.raise_for_status()
    release = resp.json()[0]
    for f in release["files"]:
        if f["os"] == "windows" and f["arch"] == "amd64" and f["kind"] == "installer":
            return LatestInfo(version=release["version"].removeprefix("go"), url=f"https://go.dev/dl/{f['filename']}",
                              filename=f["filename"], sha256=f["sha256"])
    raise LookupError("go.dev lists no windows/amd64 installer")


def _go_state() -> InstalledState:
    if not _GO_EXE.is_file():
        return InstalledState(installed=False)
    return InstalledState(True, _command_version(_GO_EXE, ["version"], r"go version go([\d.]+)"))


def _go_install(ctx: InstallContext) -> bool:
    latest = _go_resolve()
    file = download(latest.url, ctx.temp_dir, latest.filename, f"Go {latest.version}", ctx.dry_run, ctx.progress_cb,
                    trust=Trust(publishers=("Google",), sha256=latest.sha256))
    if not file:
        return False
    return run_msi(file, ["/qn", "/norestart"], f"Go {latest.version}", ctx.dry_run)


# ---------------------------------------------------------------------------
# Rust (rustup-init, then rustup downloads the stable toolchain)
# ---------------------------------------------------------------------------

_RUSTUP_URL = "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe"
_CARGO_BIN = Path.home() / ".cargo" / "bin"


def _rust_resolve() -> LatestInfo:
    toml = http_cache.get("https://static.rust-lang.org/dist/channel-rust-stable.toml", headers=_UA, timeout=20)
    toml.raise_for_status()
    match = re.search(r'\[pkg\.rust\]\s*version\s*=\s*"([\d.]+)', toml.text)
    if not match:
        raise LookupError("couldn't read the stable Rust version")
    digest = http_cache.get(_RUSTUP_URL + ".sha256", headers=_UA, timeout=15)
    digest.raise_for_status()
    sha = digest.text.split()[0].lower()
    return LatestInfo(version=match.group(1), url=_RUSTUP_URL, filename=f"rustup-init-{sha[:12]}.exe", sha256=sha)


def _rust_state() -> InstalledState:
    rustc = _CARGO_BIN / "rustc.exe"
    if not rustc.is_file():
        return InstalledState(installed=False)
    return InstalledState(True, _command_version(rustc, ["--version"], r"rustc ([\d.]+)"))


def _rust_install(ctx: InstallContext) -> bool:
    latest = _rust_resolve()
    file = download(latest.url, ctx.temp_dir, latest.filename, "rustup", ctx.dry_run, ctx.progress_cb,
                    trust=Trust(sha256=latest.sha256))
    if not file:
        return False
    # -y: no prompts. rustup edits the user's PATH itself and fetches the toolchain (hundreds of MB).
    return run_exe(file, ["-y", "--default-toolchain", "stable", "--profile", "default"],
                   f"Rust {latest.version}", ctx.dry_run, timeout=3600)


def _rust_uninstall(ctx: InstallContext) -> bool:
    rustup = _CARGO_BIN / "rustup.exe"
    if not rustup.is_file():
        get_logger().fail("rustup.exe not found - nothing to uninstall")
        return False
    return _run_uninstall_command([str(rustup), "self", "uninstall", "-y"], "Rust", ctx)


# ---------------------------------------------------------------------------
# uv (portable: a handful of exes in a zip)
# ---------------------------------------------------------------------------

_UV_DIR = PROGRAM_FILES / "uv"
_UV_PATTERN = re.compile(r"^uv-x86_64-pc-windows-msvc\.zip$")
_UV_FALLBACK = LatestInfo(
    "0.13.1", "https://github.com/astral-sh/uv/releases/download/0.13.1/uv-x86_64-pc-windows-msvc.zip",
    "uv-x86_64-pc-windows-msvc.zip", "3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672",
)


def _uv_resolve() -> LatestInfo:
    return _github_latest("astral-sh/uv", _UV_PATTERN, lambda tag: tag.lstrip("v"), _UV_FALLBACK)


def _uv_state() -> InstalledState:
    exe = _UV_DIR / "uv.exe"
    if not exe.is_file():
        return InstalledState(installed=False)
    return InstalledState(True, _command_version(exe, ["--version"], r"uv ([\d.]+)"))


def _uv_install(ctx: InstallContext) -> bool:
    log = get_logger()
    latest = _uv_resolve()
    # Version in the cache name: the asset's filename never changes between releases.
    zip_path = download(latest.url, ctx.temp_dir, f"uv-{latest.version}.zip", f"uv {latest.version}", ctx.dry_run,
                        ctx.progress_cb, trust=Trust(sha256=latest.sha256))
    if not zip_path:
        return False
    if ctx.dry_run:
        log.dry(f"Would place uv's executables in {_UV_DIR} and add it to PATH")
        return True
    if not _place_zip_exes(zip_path, ctx.temp_dir / "uv_extract", _UV_DIR):
        return False
    if not path_backup.add_directory_to_path(_UV_DIR):
        log.status(f"WARNING: could not add {_UV_DIR} to PATH - you may need to add it manually")
    return True


def _uv_uninstall(ctx: InstallContext) -> bool:
    log = get_logger()
    if ctx.dry_run:
        log.dry(f"Would delete {_UV_DIR} and remove it from PATH")
        return True
    if not path_backup.remove_directory_from_path(_UV_DIR):
        log.status(f"WARNING: could not remove {_UV_DIR} from PATH - you may need to remove it manually")
    return _remove_tree(_UV_DIR, "uv", ctx)


# ---------------------------------------------------------------------------
# Ghidra (portable: a big zip with its own top-level folder)
# ---------------------------------------------------------------------------

_GHIDRA_DIR = PROGRAM_FILES / "Ghidra"
_GHIDRA_PATTERN = re.compile(r"^ghidra_[\d.]+_PUBLIC_\d+\.zip$")
_GHIDRA_FALLBACK = LatestInfo(
    "12.1.4",
    "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip",
    "ghidra_12.1.4_PUBLIC_20260921.zip", "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db",
)


def _ghidra_resolve() -> LatestInfo:
    return _github_latest(
        "NationalSecurityAgency/ghidra", _GHIDRA_PATTERN,
        lambda tag: (re.search(r"Ghidra_([\d.]+)_build", tag) or re.search(r"([\d.]+)", tag)).group(1), _GHIDRA_FALLBACK,
    )


def _ghidra_installs() -> List[Path]:
    if not _GHIDRA_DIR.is_dir():
        return []
    found = [d for d in _GHIDRA_DIR.glob("ghidra_*") if (d / "ghidraRun.bat").is_file()]
    return sorted(found, key=lambda d: [int(p) for p in re.findall(r"\d+", d.name)[:3]], reverse=True)


def _ghidra_state() -> InstalledState:
    installs = _ghidra_installs()
    if not installs:
        return InstalledState(installed=False)
    match = re.search(r"ghidra_([\d.]+?)_", installs[0].name)
    return InstalledState(True, match.group(1) if match else installs[0].name)


def _ghidra_location() -> Optional[Path]:
    installs = _ghidra_installs()
    return installs[0] if installs else None


def _ghidra_install(ctx: InstallContext) -> bool:
    log = get_logger()
    latest = _ghidra_resolve()
    zip_path = download(latest.url, ctx.temp_dir, latest.filename, f"Ghidra {latest.version}", ctx.dry_run,
                        ctx.progress_cb, trust=Trust(sha256=latest.sha256))
    if not zip_path:
        return False
    if ctx.dry_run:
        log.dry(f"Would extract Ghidra into {_GHIDRA_DIR}")
        return True
    return _extract_zip_tree(zip_path, _GHIDRA_DIR)


def _ghidra_uninstall(ctx: InstallContext) -> bool:
    installs = _ghidra_installs()
    if not installs:
        get_logger().fail("No Ghidra install found")
        return False
    ok = all(_remove_tree(d, "Ghidra", ctx) for d in installs)
    if ok and not ctx.dry_run:
        try:
            _GHIDRA_DIR.rmdir()
        except OSError:
            pass
    return ok


# ---------------------------------------------------------------------------
# the catalog
# ---------------------------------------------------------------------------

def build_catalog() -> List[Component]:
    return [
        # --- Dev Tools
        Component(
            "terminal", "Windows Terminal", "Dev Tools", _terminal_state, _terminal_install, _terminal_resolve,
            note="Installed for the current user. The bundled terminal profile (Extras) needs this installed first.",
        ),
        _winget_component(
            "msys2", "MSYS2", "Dev Tools", "MSYS2.MSYS2", _msys2_state, location=_msys2_location,
            note="Installs to C:\\msys64 (the bundled Windows Terminal profile expects that path).",
        ),
        _winget_component(
            "innosetup", "Inno Setup", "Dev Tools", "JRSoftware.InnoSetup", _inno_state,
            note="winget installs the stable 6.x line.",
        ),
        Component(
            "ghidra", "Ghidra", "Dev Tools", _ghidra_state, _ghidra_install, _ghidra_resolve,
            uninstall=_ghidra_uninstall, optional=True, location=_ghidra_location,
            note="Portable - extracted to Program Files\\Ghidra, run ghidraRun.bat. Needs a JDK 21 (install Temurin JDK 21 too).",
        ),

        # --- Python
        Component(
            "uv", "uv (fast Python package manager)", "Python", _uv_state, _uv_install, _uv_resolve,
            path_entry=lambda: _UV_DIR, uninstall=_uv_uninstall, optional=True,
            note="Portable - uv, uvx and uvw go in Program Files\\uv, which is added to PATH.",
        ),

        # --- Go & Rust
        Component(
            "go", "Go", "Go & Rust", _go_state, _go_install, _go_resolve,
            path_entry=lambda: _GO_EXE.parent, uninstall=_generic_registry_uninstall(re.compile(r"^Go Programming Language"), "Go"),
            optional=True,
        ),
        Component(
            "rust", "Rust (rustup + stable toolchain)", "Go & Rust", _rust_state, _rust_install, _rust_resolve,
            path_entry=lambda: _CARGO_BIN, uninstall=_rust_uninstall, optional=True,
            note="Installs for the current user (%USERPROFILE%\\.cargo) and downloads the toolchain, which takes a while. "
                 "Linking needs the Microsoft C++ build tools (Visual Studio Build Tools).",
        ),

        # --- Legacy Game Support
        Component(
            "directplay", "DirectPlay (legacy networking for old games)", "Legacy Game Support",
            _directplay_state, lambda ctx: _dism_feature("DirectPlay", True, ctx),
            uninstall=lambda ctx: _dism_feature("DirectPlay", False, ctx),
            note="A Windows optional feature, switched on with dism.exe. May need a restart.",
        ),
        Component(
            "xna40", "Microsoft XNA Framework 4.0", "Legacy Game Support",
            lambda: _entry_state(_XNA_PATTERN), _xna_install,
            uninstall=_generic_registry_uninstall(re.compile(_XNA_PATTERN), "XNA Framework 4.0"),
            note="Needed by many indie games from the XNA era.",
        ),
        _winget_component(
            "physx", "NVIDIA PhysX System Software", "Legacy Game Support", "Nvidia.PhysX", _physx_state,
            note="Legacy GPU-accelerated physics for older games; harmless on non-NVIDIA machines.",
        ),

        # --- Apps (optional: never pre-checked)
        Component(
            "chrome", "Google Chrome", "Apps", _chrome_state, _chrome_install,
            uninstall=_generic_registry_uninstall(re.compile(r"^Google Chrome$"), "Google Chrome"), optional=True,
            location=lambda: (_chrome_exe().parent if _chrome_exe() else None),
            note="Updates itself, so there's no 'latest version' to compare against.",
        ),
        _winget_component(
            "discord", "Discord", "Apps", "Discord.Discord", _discord_state,
            note="Installs per-user and updates itself.",
        ),
        _winget_component(
            "anydesk", "AnyDesk", "Apps", "AnyDesk.AnyDesk", _anydesk_state,
        ),
        _winget_component(
            "claude", "Claude (desktop app)", "Apps", "Anthropic.Claude", _claude_state,
            note="Installs for the current user and updates itself.",
        ),
    ]
