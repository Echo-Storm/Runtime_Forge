# Runtime Forge — handoff notes

For whoever (human or Claude) picks this up next. Written at v0.4.0, updated for v0.4.1 (unreleased).

## Where things stand

- **App:** PyQt6 desktop GUI that scans, installs, updates and uninstalls 72 Windows
  runtimes / dev tools / apps. Dark + light theme (follows Windows). See `README.md`.
- **Repo:** <https://github.com/Echo-Storm/Runtime_Forge>, branch `main`, public.
- **Releases:** v0.2.0, v0.3.0, v0.4.0 (v0.4.1 is committed, not yet released; v0.1.0 was deleted — its installer had been
  built from a stale `dist/`). Latest is v0.4.0.
- **Tests:** 22 standalone scripts, `venv\Scripts\python.exe tools\run_tests.py` → all pass.
- **First real run (v0.4.0, elevated, on the author's machine — see the log summary below):**
  13 installs succeeded, 3 were falsely reported failed (DirectPlay, VC++ 2015-2022 x86/x64 —
  detection bugs, fixed in 0.4.1). The log lives in `%LOCALAPPDATA%\RuntimeForge\RuntimeForge_Log_*.txt`.

## Map of the code

```
runtime_forge.py        entry point
core/
  definitions.py        the core registry: Component dataclass, build_components(), VC++/.NET/JDK/
                        Python/dev-tool installers, uninstall helpers, CATEGORY_ORDER
  catalog.py            the v0.4.0/0.4.1 additions (Terminal, DirectPlay, XNA, PhysX, uv, Go, Rust, Ghidra,
                        MSYS2, Inno Setup, Chrome, and ~16 winget-backed apps); winget-backed factory
  downloader.py         download() + Trust(publishers, sha256); verify on fresh AND cached files;
                        reverify() right before execution
  signature.py          WinVerifyTrust via ctypes, signer CN/O extraction, publisher allowlist
  installer_runner.py   run_exe / run_msi (re-verify, exit-code handling, timeout)
  version_resolvers.py  GitHub / Adoptium / Node lookups, LatestInfo(version,url,filename,sha256)
  http_cache.py         lookups cache: in-memory single-flight + on-disk ETag copies that survive
                        GitHub's rate limit (`http_cache.json` in the data folder)
  checks.py             registry/PE/command probes; one-read registry snapshot; appx_package_version()
  path_backup.py / profiles.py / logger.py / paths.py
ui/
  main_window.py        the window (tree, toolbar, tabs, action bar, theme switching)
  theme.py              DARK / LIGHT palettes + the one stylesheet builder
  workers.py            ScanWorker (concurrent), InstallWorker, UninstallWorker, AppUpdateCheck
tools/                  run_tests, verify_downloads, screenshot, inspect_dll_version, gen_* (see README)
tests/                  one script per feature/fix; each prints name: True/False + ALL_OK
installer/RuntimeForge.iss   Inno Setup script
assets/                 icon, banner, screenshots, tick/dash/chevron images, Windows Terminal profile
```

### Ideas that shape the code

- **Trust model.** Every download carries a `Trust`: an Authenticode publisher allowlist and/or a
  SHA-256 (GitHub release digest, vendor JSON, or pinned in source). Failures are never retried.
  Unsigned vendors (7-Zip, LLVM, jq, ninja, OpenAL Soft, uv, Ghidra, rustup) are hash-only.
  winget-backed components rely on winget's manifest hash instead.
- **`optional` components** (apps, Go, Rust, uv, Ghidra, MSYS2, Inno Setup, PhysX) are never
  pre-checked by the first scan or *Select needed* (an update to an installed one still is).
- **Status "kinds"** (ok / update / missing / busy / fail / skip / warn / checking) are stored on
  tree items so a theme switch can recolor them (`_restyle_items`).
- **Data location:** installed copy → `%LOCALAPPDATA%\RuntimeForge`; source or `portable.txt` →
  next to the app. `RUNTIME_FORGE_DATA_DIR` overrides (tests and `tools/screenshot.py` use it).
  Installer *staging* stays beside the exe on purpose (it's executed elevated — must not be
  user-writable).

## Releasing (the exact recipe)

1. Bump the version in three places: `ui/main_window.py` (`APP_VERSION`), `installer/RuntimeForge.iss`
   (`#define AppVersion` + the comment on line 12), and the `CHANGELOG.md` heading.
2. `venv\Scripts\python.exe tools\run_tests.py` — all green.
3. Build **with the admin manifest** (make sure `RF_NO_ADMIN` is *unset*):
   `venv\Scripts\python.exe -m PyInstaller RuntimeForge.spec --clean --noconfirm`
   **Never** use `venv\Scripts\pyinstaller.exe` — that launcher silently does nothing when the
   venv has been moved, and you end up packaging a stale `dist/` (this bit v0.1.0).
4. Verify the bundle: all `core.*`/`ui.*` modules are in `build\RuntimeForge\PYZ-00.pyz`
   (use `PyInstaller.archive.readers.ZlibArchiveReader`), `dist\RuntimeForge\_internal\assets`
   has every image + `windows_terminal_settings.json`, and the exe contains `requireAdministrator`.
5. Smoke-test a non-elevated build: `set RF_NO_ADMIN=1`, build with
   `--distpath dist_test --workpath build_test`, launch it, confirm a log appears in
   `%LOCALAPPDATA%\RuntimeForge` and it scans; kill it; delete `dist_test`, `build_test`, and
   `%LOCALAPPDATA%\RuntimeForge` (only if it didn't exist before).
6. Installer: `"%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" installer\RuntimeForge.iss`
   → `dist_installer\RuntimeForge-Setup-<ver>.exe`.
7. `git push`, then `gh release create v<ver> dist_installer\RuntimeForge-Setup-<ver>.exe --target main --title ... --notes ...`.

## Gotchas

- Use `python -m pip` / `python -m PyInstaller`, never the `venv\Scripts\*.exe` launchers.
- GitHub's unauthenticated limit is 60 requests/hour; a few scans exhaust it and the app falls
  back to pinned versions. Set `GITHUB_TOKEN` (or `GH_TOKEN=$(gh auth token)`) when developing.
  The token is only ever sent to `api.github.com`.
- `tools/verify_downloads.py` downloads ~1.5 GB for everything; use `--only` / `--skip`.
  It stubs every installer, `winget`, `dism` and file placement — it never installs anything.
- Git prints "LF will be replaced by CRLF" warnings on every add; harmless (see `.gitattributes`).
- python.org stops shipping Windows installers once a series goes security-only: 3.10–3.12 are
  pinned to their *last installer* releases (3.10.11 / 3.11.9 / 3.12.10). `verify_downloads`
  catches this kind of drift.
- Claude desktop is an **MSIX** package, so it's found through the registry's AppModel
  repository (`checks.appx_package_version`), not Programs-and-Features. Same for Terminal.
- `api.adoptium.net` resets TLS handshakes from Python's OpenSSL on some machines (curl works);
  Temurin is resolved from the `temurin<N>-binaries` GitHub releases instead.
- Only the **packaged** app checks for newer releases; a source checkout doesn't
  (`RF_FORCE_UPDATE_CHECK=1` forces it).

## What the first real run showed (v0.4.0 log)

Verified working end to end, elevated: **Vulkan, XNA 4.0, .NET 10 ASP.NET + Desktop runtimes,
.NET 8 SDK (fresh) + .NET 10 SDK (update), Python 3.13 update, uv, Node.js, VS Code update,
ninja, jq, Windows Terminal update** — signatures/hashes all passed, post-install verification
passed. The signer for the .NET installers reads ".NET (Microsoft Corporation)", which the
allowlist matches on the organization.

Found and fixed in 0.4.1:
- DirectPlay: dism succeeded but detection looked for a 64-bit `dplayx.dll` that doesn't exist.
- VC++ 2015-2022: exit code 1638 ("a newer version is installed") is treated as success by
  `run_exe`, but detection only knew the old "2015-2022" display name, not "v14".
- GitHub's unauthenticated rate limit was hit within minutes (the app fell back to pinned versions
  and, for Temurin, to an Adoptium API that fails TLS from Python) → disk ETag cache.

## Still untested — check these when you run 0.4.1

(Verified offline only: downloads, hashes, signatures, detection, command construction.)

- [ ] The **installer itself** (UAC prompt, Start Menu shortcut, uninstall).
- [ ] **Rust**: `rustup-init -y …` (needs the MSVC build tools to *link*); `rustup self uninstall`.
- [ ] **Ghidra**: ~500 MB extraction into `Program Files\Ghidra`; needs JDK 21.
- [ ] **Go** MSI (PATH, uninstall via the registry entry), **Chrome** enterprise MSI.
- [ ] The **winget-backed** set — Discord, AnyDesk, Claude, MSYS2, Inno Setup, PhysX, Firefox, Edge,
      OneDrive, Windows App, Steam, Epic, K-Lite, IrfanView, Notepad++, Sublime. Command:
      `winget install --id … -e --silent --accept-package-agreements --accept-source-agreements
      --disable-interactivity`. Watch exit codes, per-user installs under an elevated process, and
      the detection patterns in `catalog.py`. **Windows App** detection asks `winget list` (it
      leaves no registry entry we could verify) — check it flips to "Installed" after installing.
- [ ] *Optional* behavior on a fresh machine: the first scan pre-checks only non-optional missing items.
- [ ] The status-bar "v0.x available" button once a newer release than the running one exists.
- [ ] Uninstall paths for the new components (none have been exercised).

## What's next (suggested order)

1. Whatever the test pass above turns up.
2. **Declarative component specs** — `definitions.py` is ~1,800 lines and ~15 components repeat
   resolve → download → verify → run. A small spec type (like the winget factory in
   `catalog.py`) would make a new tool a few lines, and could load from a JSON catalog.
3. **CI**: GitHub Actions on `windows-latest` running `tools/run_tests.py`, and building the
   installer + attaching it to a release on tag (needs Inno Setup via choco).
4. **Windows Terminal profile merge** instead of replace (merge profiles by GUID; keep the user's own).
5. **Code signing** for the exe/installer (SmartScreen warns today).
6. **On-demand elevation**: launch un-elevated and only elevate when something needs it
   (the manifest currently forces admin; a prototype idea is a `requires_admin` flag per component).
7. Update detection for the winget-backed apps (winget's manifests lag the vendors, so a naive
   compare would nag forever — needs care).
8. ARM64 Windows (everything assumes x64), Python 3.15 when it ships, more tools from the wishlist
   (Notepad++, PowerToys, Sysinternals, mpv, ffmpeg).
