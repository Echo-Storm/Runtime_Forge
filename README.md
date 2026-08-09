AIO Runtime Installer
======================

A Qt6 (PyQt6) desktop GUI for the same install list as the original AIO
Runtime & Dev Tool Installer PowerShell script — one-click install of the
legacy and modern runtimes, libraries, and dev tools needed for old games,
modern apps, and build environments on Windows 11 — with a real interface
on top instead of a console.

Author: XechostormX

What's different from the PowerShell version
----------------------------------------------
- **See what's already installed** before doing anything — every component
  is scanned on launch and shows its installed version (and, where a newer
  release exists, what's available) instead of a plain yes/no.
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
  real install run (not per component), restorable from a dropdown with a
  before/after preview. A safety net for the rare case a batch of installs
  (or anything else) leaves PATH in a bad state — restoring itself takes a
  fresh backup first, so it's never a one-way door either.
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

Dev tools
---------
- `tools/gen_icon.py` — regenerates `assets/icon.ico`/`icon.png`. Needs
  Pillow (`pip install -r requirements-dev.txt`).
- `tools/inspect_dll_version.py <path> [field ...]` — prints a DLL/EXE's PE
  VERSIONINFO fields (ProductName, ProductVersion, etc). This is what caught
  the OpenAL false-positive (an NVIDIA-bundled OpenAL32.dll passing a
  filename-only check) — reach for it before guessing at a detection fix
  when two binaries share a filename but not an identity.
- `tests/test_profiles_ui.py` — drives a real MainWindow instance to
  exercise the Profiles feature end to end (not a pytest suite, run
  directly: `venv\Scripts\python.exe tests\test_profiles_ui.py`).

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

**Java (Temurin JDK)** — 21, 17, and 8, resolved against Adoptium's latest
API per major version.

**Python** — 3.10, 3.11, 3.12, 3.13 (pinned patch versions, all-users
install with PATH and the launcher).

**Dev Tools** — PowerShell 7, Git for Windows, Node.js (LTS), CMake, and
Visual Studio Code — each resolved to its latest release/LTS at scan time
via GitHub/nodejs.org APIs, with a pinned fallback if the API can't be
reached.

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
