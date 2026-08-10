"""
Functional test for the "Basic" default profile seeded on first run.

Run directly:
    venv\\Scripts\\python.exe tests\\test_default_profile.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from core import profiles
from core.paths import get_app_dir
from ui.main_window import MainWindow

app = QApplication(sys.argv)

results: dict[str, object] = {}
app_dir = get_app_dir()

# Clean slate — this test owns the outcome of "profiles/ is empty", so
# start from a state where that's actually true.
for f in profiles.profiles_dir(app_dir).glob("*.json"):
    f.unlink(missing_ok=True)

window = MainWindow()
window.show()


def after_scan():
    try:
        seeded = profiles.list_profiles(app_dir)
        results["exactly_one_profile_seeded"] = len(seeded) == 1
        results["seeded_profile_is_named_basic"] = seeded[0].name == profiles.DEFAULT_PROFILE_NAME if seeded else False
        results["basic_profile_appears_in_combo"] = window.profile_combo.findText("Basic") > 0

        expected_categories = {"Core Runtimes", "VC++ Redistributables", ".NET Runtimes"}
        expected_keys = {c.key for c in window.components if c.category in expected_categories} | {"python_3.13", "jdk_17"}
        results["basic_profile_has_expected_keys"] = set(seeded[0].component_keys) == expected_keys if seeded else False
        results["basic_profile_excludes_dev_tools"] = not (set(seeded[0].component_keys) & {"git", "node", "cmake", "pwsh", "vscode"}) if seeded else False
        results["basic_profile_excludes_other_python_java_versions"] = not (
            set(seeded[0].component_keys) & {"python_3.10", "python_3.11", "python_3.12", "jdk_21", "jdk_8"}
        ) if seeded else False

        # Running MainWindow again (simulating a second launch) must NOT
        # seed a second profile, or silently reset one the user renamed.
        profiles.ensure_default_profile(app_dir, window.components)
        results["second_run_does_not_duplicate_seed"] = len(profiles.list_profiles(app_dir)) == 1

        # If the user has ANY profile (even unrelated to "Basic"), seeding
        # must not fire at all.
        profiles.delete_profile(app_dir, "Basic")
        profiles.save_profile(app_dir, profiles.Profile(name="Something Else", component_keys=["git"]))
        profiles.ensure_default_profile(app_dir, window.components)
        remaining = profiles.list_profiles(app_dir)
        results["does_not_seed_when_any_profile_exists"] = len(remaining) == 1 and remaining[0].name == "Something Else"

    except Exception as e:
        import traceback
        results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

    finally:
        for f in profiles.profiles_dir(app_dir).glob("*.json"):
            f.unlink(missing_ok=True)

    for k, v in results.items():
        print(f"{k}: {v}")

    all_ok = "EXCEPTION" not in results and all(results.values())
    print("ALL_OK:", all_ok)
    app.exit(0 if all_ok else 1)


def wait_for_scan():
    if window.scan_worker is not None and window.scan_worker.isRunning():
        QTimer.singleShot(300, wait_for_scan)
    else:
        after_scan()


QTimer.singleShot(500, wait_for_scan)
sys.exit(app.exec())
