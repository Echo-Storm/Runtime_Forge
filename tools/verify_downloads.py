"""
Downloads every component's real installer through the same download() +
Trust path the app uses (hash and/or Authenticode signer), WITHOUT running
any installer or touching the system, and reports which ones verify.

Use it after changing a pinned URL/hash/publisher, or periodically to catch a
vendor changing its signing certificate or republishing a file. Needs
network; the full set is ~1.5 GB (use --skip for the big ones).

    venv\\Scripts\\python.exe tools\\verify_downloads.py [--skip key,key] [--only key,key]
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import catalog, definitions, downloader
from core.definitions import InstallContext
from core.logger import setup_logging

# Components whose install() does more than download+run (registry writes,
# copies into Program Files, DISM) - nothing to verify there that the
# download+run ones don't already cover, and not safe to execute here.
ALWAYS_SKIP = {"netfx35", "openal", "ninja", "jq", "terminal_profile"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", default="")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    skip = ALWAYS_SKIP | {k for k in args.skip.split(",") if k}
    only = {k for k in args.only.split(",") if k}

    tmp = Path(tempfile.mkdtemp(prefix="rf_verify_"))
    setup_logging(tmp)

    # Nothing is executed or installed - the "run" steps are stubbed out.
    calls = []

    def fake_run(path, args_, name, dry_run=False, **_kwargs):
        calls.append(name)
        return downloader.reverify(Path(path), name) is not False

    def still_verifies(path, *_rest):
        return downloader.reverify(Path(path), Path(path).name) is not False

    for module in (definitions, catalog):
        module.run_exe = fake_run
        module.run_msi = fake_run
        module._add_appx_package = lambda p: still_verifies(p)
    # catalog.py: nothing below may touch the machine either.
    catalog._winget_run = lambda *a, **k: True          # winget components: no download of ours to check
    catalog._dism_feature = lambda *a, **k: True
    catalog._place_zip_exes = lambda zip_path, scratch, dest: still_verifies(zip_path)
    catalog._extract_zip_tree = lambda zip_path, dest: still_verifies(zip_path)

    results = []
    for comp in definitions.build_components():
        if comp.key in skip or (only and comp.key not in only):
            continue
        print(f"== {comp.key}", flush=True)
        ctx = InstallContext(temp_dir=tmp / comp.key)
        ctx.temp_dir.mkdir(parents=True, exist_ok=True)
        calls.clear()
        try:
            ok = comp.install(ctx)
        except Exception as e:  # noqa: BLE001 - report, keep going
            print(f"   EXCEPTION: {e}")
            ok = False
        results.append((comp.key, bool(ok)))

    print("\nSummary")
    for key, ok in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {key}")
    failed = [k for k, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verified; scratch dir: {tmp}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
