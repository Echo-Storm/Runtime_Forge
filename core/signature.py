"""
Warn-only Authenticode signature check, ported from ALLTHERUNTIMES.ps1's
Test-Signature. Some legitimate tools (7za.exe) ship unsigned, so an
invalid/missing signature isn't a hard failure — just surfaced so a
tampered/MITM'd download doesn't run silently unnoticed.

Windows has no first-class pure-Python Authenticode API without fragile
native bindings, so this is the one place the installer shells out to
PowerShell — a single read-only Get-AuthenticodeSignature call, not the
install itself.
"""

import subprocess

from core.logger import get_logger


def check_signature(path: str, name: str) -> None:
    log = get_logger()
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-AuthenticodeSignature -LiteralPath '{path}').Status",
            ],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status = result.stdout.strip()
        if status and status != "Valid":
            log.status(f"WARNING: {name} is not Authenticode-signed (status: {status}) - proceeding anyway")
    except (OSError, subprocess.SubprocessError):
        pass
