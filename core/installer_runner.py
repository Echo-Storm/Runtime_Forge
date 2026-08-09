"""
Runs downloaded .exe/.msi installers, ported from ALLTHERUNTIMES.ps1's
Run-Exe / Run-Msi. Exit codes 3010/1641/1638 are "success, reboot required/
pending" from Windows Installer — treated as success same as the original,
since no install in this list forces an immediate reboot (/norestart
everywhere).
"""

import subprocess
from pathlib import Path
from typing import List

from core.logger import get_logger
from core.signature import check_signature

SUCCESS_CODES = {0, 3010, 1641, 1638}


def run_exe(path: Path, args: List[str], name: str, dry_run: bool = False) -> bool:
    log = get_logger()
    if dry_run:
        log.dry(f"Would run: {name}  ({path} {' '.join(args)})")
        return True
    if not path.is_file():
        log.fail(f"Missing: {path}")
        return False

    check_signature(str(path), name)
    log.status(f"Running: {name}")
    try:
        result = subprocess.run(
            [str(path), *args],
            timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.status(f"       Exit code: {result.returncode}")
        return result.returncode in SUCCESS_CODES
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"Exception: {e}")
        return False


def run_msi(path: Path, args: List[str], name: str, dry_run: bool = False) -> bool:
    log = get_logger()
    if dry_run:
        log.dry(f"Would run MSI: {name}  ({path} {' '.join(args)})")
        return True
    if not path.is_file():
        log.fail(f"Missing: {path}")
        return False

    check_signature(str(path), name)
    log.status(f"Running MSI: {name}")
    try:
        result = subprocess.run(
            ["msiexec.exe", "/i", str(path), *args],
            timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.status(f"       Exit code: {result.returncode}")
        return result.returncode in SUCCESS_CODES
    except (OSError, subprocess.SubprocessError) as e:
        log.fail(f"Exception: {e}")
        return False
