# Security policy

Runtime Forge downloads and runs installers with administrator rights, so security
reports are taken seriously.

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting:
<https://github.com/Echo-Storm/Runtime_Forge/security/advisories/new>

Helpful details: the version (window title), what you did, what you expected, and — if it
involves a download — which component and URL. You'll get an answer as soon as I can; fixes
for real vulnerabilities go out as a new release with a note in the changelog.

## Supported versions

Only the [latest release](https://github.com/Echo-Storm/Runtime_Forge/releases/latest).
The app tells you in the status bar when a newer one exists.

## How the app protects you (and where its limits are)

- Every installer is verified **before it runs and again immediately before execution**:
  a valid Authenticode signature from the expected publisher (via `WinVerifyTrust`) and/or a
  SHA-256 (GitHub's published digest, a vendor-published hash, or one pinned in the source).
  A failed check discards the file and is never retried.
- Packages installed through `winget` are checked by winget against its reviewed manifest hash.
- Installer staging lives beside the exe (admin-writable only) — never in a user-writable folder.
- `data/versions.json` (refreshed daily by `.github/workflows/update-versions.yml`) only *selects*
  a version and supplies its hash; entries must point at `https://github.com/`, be well-formed and
  recent, or they're ignored. Anything it selects is still verified as above.
- PATH is backed up before any real install or PATH change, and restorable from the app.
- The app talks only to the vendors' own download and version-lookup hosts and to GitHub (the version
  catalog and the "newer release" notice — switch the latter off in the ☰ menu). No telemetry.

Known limits: the installer and exe are **not code-signed** (SmartScreen will warn), and
unsigned vendors (7-Zip, LLVM, jq, ninja, uv, Ghidra, rustup, OpenAL Soft) are verified by hash only.
