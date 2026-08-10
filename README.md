<p align="center"><img src="assets/banner.png" alt="AIO Runtime Installer Banner"></p>

AIO Runtime Installer
======================

<p align="center">
<img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2011-0078D6">
<img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB">
<img alt="PyQt6" src="https://img.shields.io/badge/UI-PyQt6-41CD52">
<img alt="License" src="https://img.shields.io/badge/license-MIT-informational">
</p>

A Qt6 (PyQt6) desktop GUI for the same install list as the original [AIO
Runtime & Dev Tool Installer](https://github.com/Echo-Storm/2026-AIO-Runtime-Dev-Tool-Installer)
PowerShell script — one-click install of the legacy and modern runtimes,
libraries, and dev tools needed for old games, modern apps, and build
environments on Windows 11 — with a real interface on top instead of a
console.

I write stuff when I get annoyed that something I need doesn't exist. The
PowerShell version scratched that itch for years; this is the same idea with
an actual UI on top — see what's already on the machine before touching
anything, pick exactly what you want, and never wonder what a `-DryRun`
would have done.

Author: XechostormX

Screenshot
----------
<p align="center"><img src="assets/screenshot.png" alt="AIO Runtime Installer main window — a scan in progress showing installed/outdated/missing components across .NET SDK, Java, and Python"></p>

What's different from the PowerShell version
----------------------------------------------
- **See what's already installed** before doing anything — every component
  is scanned on launch and shows its installed version (and, where a newer
  release exists, what's available) instead of a plain yes/no. Every one of
  the 47 components reports its real installed version, not just presence;
  31 have genuine update detection against a real source (a live API, or
  this app's own pinned install target). The rest — DirectX, .NET Framework
  4.8.1, WebView2, and pre-2015 VC++ redists — have no meaningful "latest
  version" to compare against at all (verified, not just not gotten to:
  DirectX's June 2010 redistributable is genuinely the final one Microsoft
  ever shipped, WebView2 self-updates in the background regardless of this
  app, etc).
- **Pick exactly what you want** — every VC++ redist year/arch, every .NET
  runtime piece, every JDK, every Python version, and every dev tool is its
  own checkbox, not an all-or-nothing run.
- **Dry Run** toggle previews every download/install without touching the
  system, same as the original's `-DryRun`.
- **Real update handling, not just detection** — checking an "update
  available" row and clicking Install actually upgrades it (PowerShell,
  Git, Node, CMake, JDKs all support in-place upgrade via their own
  installers); it doesn't just skip because something's already present.
- **PATH verification** — every install already requests PATH be updated
  (`ADD_PATH=1`, `PrependPath=1`, etc, the same flags this project's PS1
  predecessor added specifically to fix silent-install PATH gaps), but a
  flag can still silently fail to apply. After install, the tool checks
  whether the install directory is actually on PATH and flags it distinctly
  if not, instead of only confirming the software itself is present.
- **PATH backups** — one automatic snapshot of the machine + user PATH per
  real install run (not per component), plus one baseline snapshot taken
  automatically the very first time the app is ever launched, before it's
  touched anything. A manual "Backup Now" button covers everything in
  between. All restorable from a dropdown with a before/after preview —
  restoring itself takes a fresh backup first, so it's never a one-way door
  either.
- **A "Basic" profile ships seeded on first run** — broad compatibility
  coverage (Core Runtimes, all VC++ Redistributables, all .NET Runtimes),
  plus one default Python (3.13 — 3.10 reaches end-of-life in October 2026)
  and one default JDK (17 — the longer-established LTS), since most people
  just want *a* runtime of each rather than picking a version. Every
  version still stays individually selectable in the tree regardless.
  Deliberately not opinionated about the rest of dev tooling (Git/Node/
  CMake/VS Code/PowerShell). Only seeds if you have zero profiles at all —
  never overwrites or fights with anything you've built or renamed.
- **Fast scans** — version lookups (GitHub/Adoptium/nodejs.org, ~7 of them)
  run in parallel rather than one at a time; ~3.7s down to ~1s on a typical
  scan. Presence checks stay sequential since they're already fast and, for
  the install side, several installers here share Windows Installer's
  single global lock — parallelizing *those* would risk real install
  failures for a small time win, so only the genuinely parallelizable part
  (independent network calls) is.
- Fully Python install engine — no PowerShell dependency at runtime, aside
  from a single narrow read-only Authenticode signature check and the
  winget `.msixbundle` install step (Windows has no other ergonomic API for
  either). Everything else runs `msiexec.exe`, `dism.exe`, or the vendor's
  own downloaded installer directly via `subprocess`, exactly like the
  original.
- Requests admin elevation automatically via the packaged .exe's embedded
  manifest — no separate elevation batch file.

Running from source
--------------------
```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python aio_runtime_installer.py
```
Real installs need admin rights (most write to `HKLM`, `Program Files`, or
`System32`) — launch an elevated terminal first, or build the exe (below),
which prompts for elevation on its own. Running un-elevated is fine for
scanning and Dry Run.

Building the .exe
------------------
```
venv\Scripts\pip install pyinstaller
venv\Scripts\pyinstaller.exe AIORuntimeInstaller.spec --clean
```
Output lands in `dist\AIORuntimeInstaller\` — copy the whole folder to
distribute. It's portable: settings (`AIORuntimeInstaller.ini`) and log
files are written next to the exe, nothing touches the registry except the
components you choose to install.

Building the Windows installer
-------------------------------
The `dist\AIORuntimeInstaller\` folder above is portable but has no Start
Menu entry and no uninstaller. `installer\AIORuntimeInstaller.iss` (an
[Inno Setup](https://jrsoftware.org/isinfo.php) script) wraps it into a real
installer — Program Files install, Start Menu shortcut, uninstaller. Build
the `dist\` folder first (above), then:
```
"<path to>\ISCC.exe" installer\AIORuntimeInstaller.iss
```
Output lands in `dist_installer\AIORuntimeInstaller-Setup-<version>.exe`
(gitignored — the `.iss` script is what's tracked, not the built installer
binary). The installer requires admin rights, same as the app itself
already does on every launch via its embedded manifest — this is a
Start-Menu, run-occasionally desktop app, so deliberately no desktop icon
task, no auto-start entry, and no tray icon/background service.

Dev tools
---------
- `tools/gen_icon.py` — regenerates `assets/icon.ico`/`icon.png`. Needs
  Pillow (`pip install -r requirements-dev.txt`).
- `tools/inspect_dll_version.py <path> [field ...]` — prints a DLL/EXE's PE
  VERSIONINFO fields (ProductName, ProductVersion, etc). This is what caught
  the OpenAL false-positive (an NVIDIA-bundled OpenAL32.dll passing a
  filename-only check) — reach for it before guessing at a detection fix
  when two binaries share a filename but not an identity.
- `tests/` — one script per fix/feature, each driving a real MainWindow
  (or component registry) instance directly rather than mocking anything.
  Not a pytest suite — run any of them directly:
  `venv\Scripts\python.exe tests\<name>.py`. Prints `ALL_OK: True/False`
  and exits accordingly.

What It Installs / Enables
-----------------------------------------------
Same list as the original, grouped for the tree view:

**Core Runtimes** — winget, .NET Framework 3.5, DirectX June 2010 (full
legacy DirectX 9.0c via DXSETUP), OpenAL (plants the Legacy compatibility
registry key old installers check for, then overwrites the actual DLL with
OpenAL Soft's modern implementation — verified by reading the DLL's own
version resource, not just its filename), Vulkan Runtime, Microsoft Edge
WebView2 Runtime.

**VC++ Redistributables** — 2005 through 2015–2022, x86 and x64 (12 rows),
the 2015–2022 pair always resolving to the latest evergreen release.

**.NET Runtimes** — Framework 4.8.1, plus .NET 8/9/10 ASP.NET Core + Desktop
Runtimes (6 and 7 are intentionally omitted — both are past end-of-support).

**.NET SDK** — 8, 9, and 10, for actually building .NET apps rather than
just running them. Same Microsoft releases-metadata API as the runtimes
above (it has a `latest-sdk` field per channel alongside `latest-runtime`).

**Java (Temurin JDK)** — 21, 17, and 8, resolved against Adoptium's latest
API per major version.

**Python** — 3.10, 3.11, 3.12, 3.13 (pinned patch versions, all-users
install with PATH and the launcher).

**Dev Tools** — PowerShell 7, Git for Windows, Node.js (LTS), CMake, Visual
Studio Code, GitHub CLI, LLVM/Clang, ninja, and jq — each resolved to its
latest release/LTS at scan time via GitHub/nodejs.org/Microsoft APIs, with
a pinned fallback if the API can't be reached. ninja and jq ship as a raw
binary/zip with no installer at all — this app places the binary itself
and adds its folder to PATH directly (`core/path_backup.add_directory_to_path`),
the only two components that need to.

**Archive Tools** — 7-Zip and WinRAR. A deliberately narrow exception to
this app's dev/runtime-tool scope, not a step toward a general app
installer — both are close to universally needed regardless of what the
machine is otherwise for. Neither publishes a live "latest version" API
(confirmed unreliable for both during research — a scraped download page
that doesn't reflect the real current release is worse than no check at
all), so both are hand-pinned like Python rather than tracked live. WinRAR
is shareware (nags for a license after the 40-day trial, never actually
expires) — installing it here doesn't change that.

**Extras** — a curated, color-coded Windows Terminal profile: one entry per
Python version, a Node REPL, a JShell (JDK 21) REPL, Git Bash, MSYS2 (hidden
by default, only useful if you have MSYS2), VS 2022 dev consoles, plus
elevated variants of the shells. Bundled with this app
(`assets/windows_terminal_settings.json`) rather than read from its
personal OneDrive backup location, so it's fully self-contained and works
on a fresh machine that hasn't synced that folder yet. Detected via SHA256
comparison against the live `settings.json` — not just "does a settings
file exist," but "does it match exactly what this app would install."
Never overwrites an existing settings.json without backing it up first
(`settings.json.bak_<timestamp>`, right next to the real file) — this is
a personal config file, not something to silently discard.

Behavior Notes
--------------
- Every component is re-verified after install using the same presence
  check that decides whether to skip it — "Installed" in the summary only
  ever means "confirmed present," not just "the installer's exit code
  looked fine."
- Downloads retry up to 3 times with a 5-second delay and reject
  implausibly small files (usually an error page instead of the real
  installer).
- `temp_installers\` is created next to the exe during a real install and
  removed afterward; Dry Run touches nothing on disk or the network beyond
  logging what it would have done.
- Log files (`AIORuntimeInstaller_Log_*.txt`) are kept next to the exe,
  newest 10 retained.
