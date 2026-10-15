# Contributing

Thanks for wanting to help. Small, focused changes with a test are easiest to merge.

## Set up

```
git clone https://github.com/Echo-Storm/Runtime_Forge
cd Runtime_Forge
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe runtime_forge.py          # run from source
venv\Scripts\python.exe tools\run_tests.py        # the whole suite (offscreen, throw-away data folder)
```

Always use `venv\Scripts\python.exe -m ...` rather than the `pip.exe` / `pyinstaller.exe`
launchers (they silently misbehave if the folder was ever moved). Set `GITHUB_TOKEN`
(`$env:GITHUB_TOKEN = (gh auth token)`) when hacking on version lookups — GitHub allows only 60
anonymous requests an hour.

## Adding a component (the usual contribution)

1. Pick the pattern in `core/catalog.py`: a **winget-backed** one (`_winget_component(...)` —
   a few lines, needs the winget ID and a way to detect it) or **your own pipeline** (download →
   `Trust(publishers=…, sha256=…)` → `run_exe` / `run_msi`).
2. Every download needs integrity: the vendor's signer name in `publishers`, and/or a SHA-256
   (from the release API, the vendor, or pinned). Check the real signer with `tools/verify_downloads.py`.
3. Say whether it's `optional` (never pre-checked), add a one-line `note`, and give it an uninstall
   when there's a safe one.
4. Add detection that works on a machine where it's installed (registry Uninstall key, a file, an
   Appx package…) — verify it against your own machine.
5. Tests in `tests/` (offline: fake the network, winget and the registry), then
   `tools\verify_downloads.py --only <key>`.
6. Update the README component list and `CHANGELOG.md`.

Or just open a **Suggest a component** issue and I'll add it.

## Conventions

- The tests are standalone scripts (`name: True/False` lines, `ALL_OK:`) — see any file in `tests/`.
- Don't add telemetry, don't weaken a verification step, and don't make an installer run from a
  user-writable folder.
- `HANDOFF.md` has the architecture map, the release recipe and the gotchas.
