"""
Runs every tests/test_*.py script (they're standalone scripts that print
`ALL_OK: True/False` and exit non-zero on failure - not a pytest suite) and
prints a one-line result for each.

Each script runs in its own process with:
  - QT_QPA_PLATFORM=offscreen  (no windows flash on screen)
  - RUNTIME_FORGE_DATA_DIR=<temp dir>  (logs/profiles/PATH backups of the
    test run stay out of the project folder and your real data)
  - RUNTIME_FORGE_NO_CATALOG=1  (the published version catalog is skipped)

    venv\\Scripts\\python.exe tools\\run_tests.py            # everything
    venv\\Scripts\\python.exe tools\\run_tests.py ui speed   # only files whose name contains one of these
    venv\\Scripts\\python.exe tools\\run_tests.py -v         # show each script's output
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 300


def main() -> int:
    args = sys.argv[1:]
    verbose = "-v" in args
    filters = [a.lower() for a in args if not a.startswith("-")]

    scripts = sorted((ROOT / "tests").glob("test_*.py"))
    if filters:
        scripts = [s for s in scripts if any(f in s.stem.lower() for f in filters)]
    if not scripts:
        print("No matching test scripts.")
        return 1

    data_dir = Path(tempfile.mkdtemp(prefix="rf_tests_"))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", RUNTIME_FORGE_DATA_DIR=str(data_dir), PYTHONIOENCODING="utf-8",
               RUNTIME_FORGE_NO_CATALOG="1")  # tests use mocks or the live path, never the published catalog

    failed = []
    started = time.time()
    for script in scripts:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(script)], cwd=ROOT, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            ok = proc.returncode == 0
        except subprocess.TimeoutExpired as e:
            output = f"TIMED OUT after {TIMEOUT_SECONDS}s\n{e.stdout or ''}"
            ok = False
        status = "PASS" if ok else "FAIL"
        print(f"{status}  {script.name:<40} {time.time() - t0:5.1f}s")
        if verbose or not ok:
            interesting = [ln for ln in output.splitlines() if verbose or ": False" in ln or "Traceback" in ln or "Error" in ln]
            for line in (interesting or output.splitlines()[-8:])[-30:]:
                print(f"      {line}")
        if not ok:
            failed.append(script.name)

    shutil.rmtree(data_dir, ignore_errors=True)
    print(f"\n{len(scripts) - len(failed)}/{len(scripts)} scripts passed in {time.time() - started:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
