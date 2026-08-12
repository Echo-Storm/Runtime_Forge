"""
Regression tests for uninstall support (core/checks.py's registry-command
lookup + core/definitions.py's uninstall factories).

Never runs a real uninstall command against anything actually installed on
the test machine — the registry-driven factories are exercised against a
monkeypatched checks.find_uninstall_command_by_display_name so the test is
deterministic and doesn't depend on (or risk) real machine state. The one
factory that DOES do real filesystem/PATH work (_portable_binary_uninstall)
is exercised for real, but only against throwaway scratch paths passed in
directly — the same "real execution, safe target" precedent already used
for PATH backup/restore testing elsewhere in this suite.

Run directly:
    venv\\Scripts\\python.exe tests\\test_uninstall.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import checks, definitions, path_backup
from core.definitions import InstallContext, build_components
from core.logger import setup_logging
from core.paths import get_app_dir

app_dir = get_app_dir()
setup_logging(app_dir)

results: dict[str, object] = {}


class _FakeUninstallCommand:
    def __init__(self, display_name, quiet_command=None, raw_command=None):
        self.display_name = display_name
        self.quiet_command = quiet_command
        self.raw_command = raw_command


real_find_uninstall_command = checks.find_uninstall_command_by_display_name

try:
    # --- parse_command_line: real Windows command-line parsing quirks ---
    results["parses_quoted_path_with_args"] = checks.parse_command_line(
        r'"C:\Program Files\Git\unins000.exe" /SILENT'
    ) == [r"C:\Program Files\Git\unins000.exe", "/SILENT"]
    results["parses_msi_guid_invocation"] = checks.parse_command_line(
        r"MsiExec.exe /I{23170F69-40C1-2702-2602-000001000000}"
    ) == ["MsiExec.exe", "/I{23170F69-40C1-2702-2602-000001000000}"]
    # The exact real-world case that motivated NOT using this for bare
    # paths in _silent_flag_uninstall: an unquoted path containing a space
    # gets ambiguously split at the space, same as CreateProcess itself
    # would interpret it.
    results["ambiguous_unquoted_path_splits_at_space"] = checks.parse_command_line(
        r"C:\Program Files\WinRAR\uninstall.exe"
    ) == [r"C:\Program", r"Files\WinRAR\uninstall.exe"]

    # --- _generic_registry_uninstall: MSI GUID extraction + /I-vs-/X ---
    # Confirmed on a real machine: several real MSI packages (7-Zip,
    # Python sub-features, Temurin JDKs) register UninstallString with the
    # literal "/I{GUID}" (install/repair verb) - this must never be
    # trusted verbatim; the GUID gets extracted and /x rebuilt ourselves.
    checks.find_uninstall_command_by_display_name = lambda pattern: _FakeUninstallCommand(
        "Fake App", quiet_command=None, raw_command="MsiExec.exe /I{11111111-2222-3333-4444-555555555555}"
    )
    captured_args = {}
    real_run = definitions._run_uninstall_command
    definitions._run_uninstall_command = lambda args, name, ctx: captured_args.update(args=args) or True
    uninstaller = definitions._generic_registry_uninstall(re.compile("Fake App"), "Fake App")
    uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["msi_verb_normalized_to_uninstall_not_repair"] = captured_args["args"] == [
        "msiexec.exe", "/x", "{11111111-2222-3333-4444-555555555555}", "/qn", "/norestart",
    ]

    # QuietUninstallString, when present, is trusted outright.
    checks.find_uninstall_command_by_display_name = lambda pattern: _FakeUninstallCommand(
        "Fake App", quiet_command=r'"C:\Fake\unins.exe" /VERYSILENT'
    )
    uninstaller = definitions._generic_registry_uninstall(re.compile("Fake App"), "Fake App")
    uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["quiet_uninstall_string_used_as_is"] = captured_args["args"] == [r"C:\Fake\unins.exe", "/VERYSILENT"]

    # No registry entry at all -> fails cleanly, no command constructed.
    checks.find_uninstall_command_by_display_name = lambda pattern: None
    captured_args.clear()
    uninstaller = definitions._generic_registry_uninstall(re.compile("Nonexistent App"), "Nonexistent App")
    ok = uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["missing_registry_entry_fails_without_running_anything"] = ok is False and "args" not in captured_args

    # --- _silent_flag_uninstall: the actual bug found via dry-run testing ---
    # WinRAR's real UninstallString is unquoted despite containing a space
    # ("C:\Program Files\WinRAR\uninstall.exe") - argv-splitting it (as
    # parse_command_line correctly does for genuine multi-token commands)
    # mangled it to just "C:\Program". Confirms the fix: treat a bare
    # UninstallString as one path, not tokens to split.
    checks.find_uninstall_command_by_display_name = lambda pattern: _FakeUninstallCommand(
        "WinRAR 7.23 (64-bit)", quiet_command=None, raw_command=r"C:\Program Files\WinRAR\uninstall.exe"
    )
    captured_args.clear()
    uninstaller = definitions._silent_flag_uninstall(re.compile("WinRAR"), "WinRAR", ["/S"])
    uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["unquoted_path_with_space_not_mangled"] = captured_args["args"] == [
        r"C:\Program Files\WinRAR\uninstall.exe", "/S",
    ]

    # A quoted bare path (LLVM's real format) still works correctly too.
    checks.find_uninstall_command_by_display_name = lambda pattern: _FakeUninstallCommand(
        "LLVM", quiet_command=None, raw_command=r'"C:\Program Files\LLVM\Uninstall.exe"'
    )
    captured_args.clear()
    uninstaller = definitions._silent_flag_uninstall(re.compile("LLVM"), "LLVM", ["/S"])
    uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["quoted_bare_path_unwrapped_correctly"] = captured_args["args"] == [
        r"C:\Program Files\LLVM\Uninstall.exe", "/S",
    ]

    definitions._run_uninstall_command = real_run
    checks.find_uninstall_command_by_display_name = real_find_uninstall_command

    # --- _portable_binary_uninstall: real execution, safe scratch target ---
    scratch_dir = app_dir / "test_uninstall_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = scratch_dir / "fake.exe"
    fake_version_file = scratch_dir / "VERSION.txt"
    fake_exe.write_bytes(b"not a real exe")
    fake_version_file.write_text("1.2.3", encoding="utf-8")

    dry_uninstaller = definitions._portable_binary_uninstall(fake_exe, fake_version_file, scratch_dir, "Fake Portable")
    dry_uninstaller(InstallContext(temp_dir=app_dir, dry_run=True))
    results["dry_run_does_not_delete_files"] = fake_exe.is_file() and fake_version_file.is_file()

    real_uninstaller = definitions._portable_binary_uninstall(fake_exe, fake_version_file, scratch_dir, "Fake Portable")
    real_uninstaller(InstallContext(temp_dir=app_dir, dry_run=False))
    results["real_run_deletes_exe_and_version_file"] = not fake_exe.exists() and not fake_version_file.exists()
    # scratch_dir itself should have been cleaned up too (empty after
    # removing the two files it contained).
    results["real_run_removes_now_empty_install_dir"] = not scratch_dir.exists()

    # --- Component registry: scope decisions actually landed as intended ---
    components = {c.key: c for c in build_components()}
    uninstallable_keys = {k for k, c in components.items() if c.uninstall is not None}
    results["exactly_the_intended_components_have_uninstall"] = uninstallable_keys == {
        "netfx35",
        "net_sdk_8.0", "net_sdk_9.0", "net_sdk_10.0",
        "jdk_21", "jdk_17", "jdk_8",
        "pwsh", "git", "node", "cmake", "gh", "llvm", "ninja", "jq",
        "7zip", "winrar",
    }
    # Explicitly verify the deliberately-excluded ones stayed excluded -
    # these exclusions are load-bearing safety decisions (fragmented
    # multi-entry registrations, shared-dependency risk to other software,
    # no uninstaller ever existing), not oversights, and a future
    # component-list change silently enabling one of these should fail
    # this test rather than ship unnoticed.
    excluded = ["winget", "directx", "openal", "webview2", "vscode",
                "vc_2005_x86", "vc_2015-2022_x64",
                "net_.NET 8 ASP.NET Core Runtime", "net_.NET Framework 4.8.1",
                "python_3.13", "terminal_profile"]
    results["deliberately_excluded_components_have_no_uninstall"] = all(
        components[k].uninstall is None for k in excluded if k in components
    )

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

finally:
    checks.find_uninstall_command_by_display_name = real_find_uninstall_command
    definitions._run_uninstall_command = real_run if "real_run" in dir() else definitions._run_uninstall_command
    import shutil
    shutil.rmtree(app_dir / "test_uninstall_scratch", ignore_errors=True)

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
