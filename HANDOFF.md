# Runtime Forge — handoff notes

For whoever (human or Claude) picks this up next. Written at v0.4.0, updated for v0.4.2.

## Where things stand

- **App:** PyQt6 desktop GUI that scans, installs, updates and uninstalls 72 Windows
  runtimes / dev tools / apps. Dark + light theme (follows Windows). See `README.md`.
- **Repo:** <https://github.com/Echo-Storm/Runtime_Forge>, branch `main`, public.
- **Releases:** v0.2.0, v0.3.0, v0.4.0, v0.4.1, v0.4.2 (v0.1.0 was deleted — its installer had been
  built from a stale `dist/`). Latest is v0.4.2.
- **Tests:** 26 standalone scripts, `venv\Scripts\python.exe tools\run_tests.py` → all pass.
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
  published.py          the published catalog (data/versions.json): first stop for GitHub-hosted
                        components' latest version/url/sha256; validated; skipped with a token
  terminal_profile.py   JSONC parser + merge/is_applied for the Windows Terminal profile
  python_default.py     PEP 514 discovery + the 'make the newest Python the default' PATH plan
  java_default.py       the same for Temurin JDKs (+ JAVA_HOME repoint)
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
   `--distpath dist_test --workpath build_test`, launch it with `RUNTIME_FORGE_DATA_DIR=<temp dir>` (so it
   never touches your real data) and **no** `GITHUB_TOKEN`, confirm a log appears, the scan completes with no
   "Could not query GitHub" lines (that proves the published catalog is being used), then kill it and delete
   `dist_test`, `build_test` and the temp dir.
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

## What the first real runs showed (v0.4.0 and v0.4.1 logs)

Verified working end to end, elevated: **Vulkan, XNA 4.0, .NET 10 ASP.NET + Desktop runtimes,
.NET 8 SDK (fresh) + .NET 10 SDK (update), Python 3.13 update, uv, Node.js, VS Code update,
ninja, jq, Windows Terminal update** — signatures/hashes all passed, post-install verification
passed. The signer for the .NET installers reads ".NET (Microsoft Corporation)", which the
allowlist matches on the organization.

**v0.4.1 run (elevated): 9 installed, 0 failed** — Go (SHA-256 + Google signature), Rust
(rustup, ~20 s for the toolchain), Ghidra (extracted in ~10 s), Chrome (MSI), Windows App (via
winget; the post-install `winget list` check flipped it to Installed), .NET 10 runtimes/SDK, and
the Windows Terminal profile (backup written first). So Go, Rust, Ghidra, Chrome and one winget
install are now proven for real.

Found and fixed in 0.4.1:
- DirectPlay: dism succeeded but detection looked for a 64-bit `dplayx.dll` that doesn't exist.
- VC++ 2015-2022: exit code 1638 ("a newer version is installed") is treated as success by
  `run_exe`, but detection only knew the old "2015-2022" display name, not "v14".
- GitHub's unauthenticated rate limit was hit within minutes (the app fell back to pinned versions
  and, for Temurin, to an Adoptium API that fails TLS from Python) → disk ETag cache.

## Still untested — check these when you run 0.4.1

(Verified offline only: downloads, hashes, signatures, detection, command construction.)

- [ ] The **installer itself** (UAC prompt, Start Menu shortcut, uninstall).
- [ ] **Uninstall** paths for Rust (`rustup self uninstall`), Ghidra, Go, Chrome, uv (none exercised).
- [x] ~~Rust / Ghidra / Go / Chrome installs~~ — proven in the v0.4.1 log.
- [ ] The rest of the **winget-backed** set — Discord, AnyDesk, Claude, MSYS2, Inno Setup, PhysX, Firefox, Edge,
      OneDrive, Steam, Epic, K-Lite, IrfanView, Notepad++, Sublime (Windows App is proven). Command:
      `winget install --id … -e --silent --accept-package-agreements --accept-source-agreements
      --disable-interactivity`. Watch exit codes, per-user installs under an elevated process, and
      the detection patterns in `catalog.py`. **Windows App** detection asks `winget list` (it
      leaves no registry entry we could verify) — check it flips to "Installed" after installing.
- [ ] *Optional* behavior on a fresh machine: the first scan pre-checks only non-optional missing items.
- [ ] The status-bar "v0.x available" button once a newer release than the running one exists.
- [ ] **Make the newest Python the default** (☰ menu) on a machine with several on PATH — the plan was
      dry-run against the author's real PATH and unit-tested, but never applied elevated.

## Python default (v0.4.2)

`core/python_default.py` — discovery via PEP 514 (`HKLM/HKCU\SOFTWARE\Python\PythonCore`), a pure
`plan_make_default()` and `apply_plan()` (writes through `path_backup.write_paths`). Installs only pass
`PrependPath=1` for `definitions._NEWEST_PY`. Default always lands at the front of the **machine** PATH,
because machine entries are resolved before user entries (a per-user newest Python — like the author's
`E:\Python314` — could never win from the user PATH). Windows Terminal's bundled profile still uses
`C:\Program Files\Python3xx` paths, so a custom-folder Python has a dead profile entry (backlog).

## The v0.4.2 install log (elevated, "update everything")

12 installed, 0 failed — OpenAL, .NET 10 runtimes + SDK, JDK 8, Python 3.14 (upgraded the existing
custom-folder install in place), PowerShell 7, Git, CMake, gh, LLVM, and the Terminal profile merge
(backup written, "your own profiles and settings were kept"). What it exposed, all fixed after 0.4.2:
- ".NET 10 / OpenAL always say update available": side-by-side folders (first-match detection) and an
  OpenAL install that skipped itself when Soft was already present.
- LLVM's silent installer doesn't add itself to PATH (the app warned correctly); now it adds it.
- Updating JDK 8 put it first on PATH again (`java -version` → 1.8): every Temurin MSI has
  `FeatureEnvironment` on at INSTALLLEVEL=1. Older JDKs now install with
  `ADDLOCAL=FeatureMain,FeatureJarFileRunWith`; the Java default action repairs existing machines.
- The Python 3.14 upgrade did not re-add itself to PATH (the python.org installer doesn't on upgrade);
  that's what the Python default action is for.

## What's next (suggested order)

1. Whatever the test pass above turns up.
2. ~~A pinned `versions.json` fetched from the repo~~ — **done** (`core/published.py`, `tools/update_versions.py`,
   `.github/workflows/update-versions.yml`). Check that the workflow actually ran after the first push
   (Actions tab → *Update versions.json* → Run workflow) and that `data/versions.json` updates daily.
   It commits straight to `main`; switch to a PR if you want to review each refresh. Pushing the workflow file
   needs the `workflow` scope on your gh token (`gh auth refresh -s workflow`).
3. **Declarative component specs** — `definitions.py` is ~1,800 lines and ~15 components repeat
   resolve → download → verify → run. A small spec type (like the winget factory in
   `catalog.py`) would make a new tool a few lines, and could load from a JSON catalog.
4. **CI**: GitHub Actions on `windows-latest` running `tools/run_tests.py`, and building the
   installer + attaching it to a release on tag (needs Inno Setup via choco).
5. ~~Windows Terminal profile merge~~ — **done** (`core/terminal_profile.py`).
6. **Code signing** for the exe/installer (SmartScreen warns today).
7. **On-demand elevation**: launch un-elevated and only elevate when something needs it
   (the manifest currently forces admin; a prototype idea is a `requires_admin` flag per component).
8. Update detection for the winget-backed apps (winget's manifests lag the vendors, so a naive
   compare would nag forever — needs care).
9. ARM64 Windows (everything assumes x64), Python 3.15 when it ships, more tools from the wishlist
   (PowerToys, Sysinternals, mpv, ffmpeg, foobar2000).
