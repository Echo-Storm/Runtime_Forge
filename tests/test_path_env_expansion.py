"""
Regression test for refresh_path_env() not expanding %VAR% placeholders.

Confirmed as a real, currently-reproducible bug on the dev machine itself:
its own real HKCU\\Environment\\Path contains a literal, unexpanded
"%USERPROFILE%\\.dotnet\\tools" entry (written by dotnet's own installer) -
winreg.QueryValueEx never expands REG_EXPAND_SZ content, so anything that
trusted the raw registry value as a walkable PATH would silently never
match a real directory for entries like that one.

Monkeypatches core.checks.reg_value so this doesn't depend on what's
actually in the registry on whatever machine runs it - the fix must hold
regardless of real machine state.

Run directly:
    venv\\Scripts\\python.exe tests\\test_path_env_expansion.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import checks

results: dict[str, object] = {}
real_reg_value = checks.reg_value
real_path_env = os.environ.get("Path")

FAKE_MACHINE = r"C:\Windows\system32;C:\Windows"
FAKE_USER = r"%USERPROFILE%\.dotnet\tools;%LOCALAPPDATA%\Microsoft\WindowsApps"


def fake_reg_value(hive, subkey, name):
    if hive == "HKLM":
        return FAKE_MACHINE
    if hive == "HKCU":
        return FAKE_USER
    return None


try:
    checks.reg_value = fake_reg_value
    checks.refresh_path_env()
    combined = os.environ.get("Path", "")

    results["no_literal_percent_left_unexpanded"] = "%" not in combined
    results["userprofile_entry_expanded_to_real_path"] = (
        os.environ["USERPROFILE"] + r"\.dotnet\tools" in combined
    )
    results["localappdata_entry_expanded_to_real_path"] = (
        os.environ["LOCALAPPDATA"] + r"\Microsoft\WindowsApps" in combined
    )
    results["machine_entries_still_present"] = r"C:\Windows\system32" in combined and r"C:\Windows" in combined

except Exception as e:
    import traceback
    results["EXCEPTION"] = f"{e}\n{traceback.format_exc()}"

finally:
    checks.reg_value = real_reg_value
    if real_path_env is not None:
        os.environ["Path"] = real_path_env

for k, v in results.items():
    print(f"{k}: {v}")

all_ok = "EXCEPTION" not in results and all(results.values())
print("ALL_OK:", all_ok)
sys.exit(0 if all_ok else 1)
