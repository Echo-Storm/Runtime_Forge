"""
Regression test for the Windows Terminal Profile component. Never points
at the real live Windows Terminal settings.json — even though this
session confirmed its content is currently byte-identical to the bundled
source (so overwriting it would be a no-op today), the actual write path
(backup-then-overwrite) is exercised against a temp target instead. That's
the same discipline as never calling path_backup.restore_backup() with
real data in tests/test_path_backup.py: verifying the mechanism doesn't
require pointing it at something that matters if it goes wrong.

Run directly:
    venv\\Scripts\\python.exe tests\\test_terminal_profile.py
"""

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.definitions as definitions
from core.logger import setup_logging
from core.paths import get_data_dir

app_dir = get_data_dir()
setup_logging(app_dir)

results: dict[str, object] = {}
scratch_dir = app_dir / "test_terminal_profile_scratch"
real_target = definitions._TERMINAL_PROFILE_TARGET

try:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    fake_target = scratch_dir / "settings.json"
    definitions._TERMINAL_PROFILE_TARGET = fake_target  # patched for this test only

    source = definitions._terminal_profile_source()
    results["bundled_source_exists"] = source.is_file()

    # Nothing at the fake target yet -> not installed
    results["not_installed_when_target_missing"] = definitions._terminal_profile_is_installed().installed is False

    ctx = definitions.InstallContext(temp_dir=scratch_dir, dry_run=True)
    results["dry_run_does_not_create_file"] = definitions._terminal_profile_install(ctx) and not fake_target.is_file()

    real_ctx = definitions.InstallContext(temp_dir=scratch_dir, dry_run=False)
    install_ok = definitions._terminal_profile_install(real_ctx)
    results["real_install_reports_success"] = install_ok
    results["real_install_creates_the_file"] = fake_target.is_file()
    results["installed_content_matches_bundled_source"] = fake_target.read_bytes() == source.read_bytes()
    results["is_installed_true_after_install"] = definitions._terminal_profile_is_installed().installed is True

    # Simulate the user having their own different settings, then re-install
    # and confirm (a) it gets backed up, not silently discarded, and (b) the
    # live file is correctly detected as "not installed" beforehand.
    fake_target.write_text('{"customized": true}', encoding="utf-8")
    results["differing_content_detected_as_not_installed"] = definitions._terminal_profile_is_installed().installed is False

    definitions._terminal_profile_install(real_ctx)
    backups = list(scratch_dir.glob("settings.json.bak_*"))
    results["reinstall_creates_a_backup_of_customized_content"] = len(backups) == 1
    if backups:
        results["backup_preserves_the_customized_content"] = backups[0].read_text(encoding="utf-8") == '{"customized": true}'
    results["reinstall_restores_matching_content"] = fake_target.read_bytes() == source.read_bytes()
    results["is_installed_true_after_reinstall"] = definitions._terminal_profile_is_installed().installed is True

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

finally:
    definitions._TERMINAL_PROFILE_TARGET = real_target  # always restore, even on failure
    shutil.rmtree(scratch_dir, ignore_errors=True)

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
