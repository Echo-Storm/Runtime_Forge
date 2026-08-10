"""
Functional test for the first-launch PATH backup baseline.

Like test_path_backup.py, this only ever reads PATH and writes backup JSON
files (never calls restore_backup() with real data), so it's safe to run
against the real app_dir. Cleans up any backups it creates.

Run directly:
    venv\\Scripts\\python.exe tests\\test_first_run_path_backup.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import path_backup
from core.logger import setup_logging
from core.paths import get_app_dir

app_dir = get_app_dir()
setup_logging(app_dir)

results: dict[str, object] = {}

# Clean slate — this test owns the outcome of "no backups yet", so start
# from a state where that's actually true, same discipline as
# test_default_profile.py does for profiles/.
saved = list(path_backup.backups_dir(app_dir).glob("path_backup_*.json"))
saved_bytes = {p.name: p.read_bytes() for p in saved}
for p in saved:
    p.unlink(missing_ok=True)

try:
    results["no_backups_before"] = len(path_backup.list_backups(app_dir)) == 0

    path_backup.ensure_first_run_backup(app_dir)
    after_first = path_backup.list_backups(app_dir)
    results["first_call_creates_exactly_one_backup"] = len(after_first) == 1
    results["backup_reason_mentions_first_launch"] = "first launch" in after_first[0].reason.lower() if after_first else False

    current_machine, current_user = path_backup.read_current_path()
    results["backup_captured_current_machine_path"] = after_first[0].machine_path == current_machine if after_first else False
    results["backup_captured_current_user_path"] = after_first[0].user_path == current_user if after_first else False

    # Simulating a second launch must NOT create a second backup.
    path_backup.ensure_first_run_backup(app_dir)
    results["second_call_does_not_duplicate"] = len(path_backup.list_backups(app_dir)) == 1

    # Even a manually-created backup (not from ensure_first_run_backup
    # itself) must be enough to suppress it - same "anything already there"
    # shape as ensure_default_profile().
    for f in path_backup.backups_dir(app_dir).glob("path_backup_*.json"):
        f.unlink(missing_ok=True)
    path_backup.create_backup(app_dir, "manual backup")
    path_backup.ensure_first_run_backup(app_dir)
    remaining = path_backup.list_backups(app_dir)
    results["does_not_fire_when_any_backup_exists"] = len(remaining) == 1 and remaining[0].reason == "manual backup"

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

finally:
    for p in path_backup.backups_dir(app_dir).glob("path_backup_*.json"):
        p.unlink(missing_ok=True)
    for name, data in saved_bytes.items():
        (path_backup.backups_dir(app_dir) / name).write_bytes(data)

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
