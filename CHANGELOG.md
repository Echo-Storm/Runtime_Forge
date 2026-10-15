# Changelog

## Unreleased
- **Only the newest Python is the default.** Installing Python no longer puts every
  version on PATH (the last one installed used to win): only the newest series gets
  `PrependPath`, the older ones stay reachable with `py -3.12`.
- **☰ → "Make the newest Python the default…"** fixes a machine that already has several
  on PATH: previews the change, backs PATH up, puts the newest python.org Python first on
  the machine PATH (machine entries outrank user entries) and removes the others' folders,
  including their `%APPDATA%\Python\PythonXY` user-site folders. Nothing is uninstalled.
- Python installs are detected through the registry (PEP 514), so a Python in a custom
  folder (`E:\Python314`) now shows as installed instead of "not installed".
- **Published version catalog** (`data/versions.json`, refreshed daily by a GitHub Action):
  one request replaces ~20 GitHub API calls per scan, so the 60-an-hour limit stops
  degrading scans. Entries are validated (github.com URL, 64-hex SHA-256, matching file
  name, not older than 10 days) and downloads are verified exactly as before. A
  `GITHUB_TOKEN` or `RUNTIME_FORGE_NO_CATALOG=1` uses the live API instead.
- **LLVM was silently stuck on a pinned version**: LLVM 23.x releases only ship
  `.tar.xz` archives, not the Windows installer, so "latest release" had no installer.
  It now takes the newest stable release that does (22.1.8 today).
- **Windows Terminal profile is merged, not replaced**: your own profiles, schemes,
  keybindings and defaults are kept; ours are added or refreshed by GUID/name; "installed"
  means ours are present and current (adding your own profiles no longer flips it to
  "not installed"). The Python entries launch via `py -3.x`, so custom install folders work.
- Housekeeping: an unused import, a docstring warning in `tools/screenshot.py`.

## 0.4.1
Fixes from the first real elevated run of 0.4.0 (13 installs succeeded; 3 were
falsely reported as failed), plus the rest of the everyday apps.
- **DirectPlay** was enabled but reported as not installed: its 64-bit DLL doesn't
  exist (the feature only provides a 32-bit one). Detection now reads the servicing
  stack's own record.
- **VC++ 2015-2022 (x86/x64)** showed as missing — and "failed" after a successful
  install (exit 1638, a newer one was already present) — because current redistributables
  call themselves "Visual C++ v14 Redistributable". Detection understands both names.
- **GitHub rate limits** no longer degrade a scan: lookups are stored on disk with their
  ETags (`http_cache.json`), revalidated with conditional requests (304s are free), and the
  last good copy is used when GitHub rate-limits or is unreachable.
- **More apps** (optional): Firefox, Microsoft Edge, OneDrive, Windows App, Steam, Epic Games
  Launcher, K-Lite Codec Pack, IrfanView, plus Notepad++ and Sublime Text 4 under Dev Tools
  — 72 components.

## 0.4.0
- **Windows Terminal is now installable** (it wasn't offered before, though the
  bundled terminal profile depends on it). The profile refuses to apply when
  Terminal isn't there instead of creating an orphan settings folder.
- **Legacy Game Support**: DirectPlay, XNA Framework 4.0, NVIDIA PhysX.
- **Go & Rust** category; **uv** under Python; **MSYS2**, **Inno Setup** and
  **Ghidra** under Dev Tools.
- **Apps** (optional): Chrome, Discord, AnyDesk, Claude. Optional components are
  never pre-checked by a scan or Select needed (updates to installed ones still are).
- Components can carry a note (shown in the Details tab) and an explicit
  install location.
- Per-user installs (VS Code, MSYS2, Inno Setup 7...) are now found through the
  HKCU Uninstall key — VS Code can finally be uninstalled from the app.
- 62 components (was 48); tools/run_tests.py, tools/verify_downloads.py cover them.

## 0.3.0
- **New window.** Full-width tree (Status / Installed / Latest), search and
  All / Needs action / Installed filter, Details / Log / PATH backups tabs,
  right-click Install / Update / Reinstall, live "Install N selected" button,
  overall install progress, colour-coded log with Copy / Clear / Open.
- **Light and dark themes**, following Windows by default.
- Drag a profile `.json` onto the window to import it.
- The packaged app notices newer releases (switch off in the ☰ menu).
- Readable component names ("Visual C++ 2008 (x64)"); JDK versions shown as
  `21.0.12.8` instead of the folder name; scan warnings appear in the log.
- Windows Terminal profile gains a Python 3.14 entry.

## 0.2.0
- **Installer integrity**: every download is verified (Authenticode signer
  allowlist via `WinVerifyTrust`, and/or SHA-256) and re-verified immediately
  before it runs; failures are never retried.
- **Fixes found by `tools/verify_downloads.py`**: Python 3.10–3.12 pins
  404'd (source-only releases) → last installer releases, Python 3.14 added;
  the .NET Framework 4.8.1 link had died → offline installer; Temurin lookups
  moved to Adoptium's GitHub releases (api.adoptium.net resets TLS handshakes
  from Python).
- Logs, settings, profiles and PATH backups moved to `%LOCALAPPDATA%\RuntimeForge`
  for installed copies (`portable.txt` opts out; old data is migrated).
- Faster scans: shared HTTP cache, one registry read per scan, concurrent
  checks. `GITHUB_TOKEN` support.
- Truncated downloads are detected; winget fallback filename fixed; asset
  lookup fixed for PyInstaller 6 builds.

## 0.1.0
- First public release (the published installer turned out to have been
  packaged from a stale build; superseded by 0.2.0).
