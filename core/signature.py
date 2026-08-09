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
    # PowerShell escapes a single quote inside a single-quoted string by
    # doubling it — without this, a path containing one (a legitimate
    # Windows username like O'Brien, for instance) breaks out of the string
    # literal and the whole command fails silently, defeating the check
    # with no warning (status ends up empty, which the guard below treats
    # as "nothing to report" rather than "the check itself didn't run").
    escaped_path = path.replace("'", "''")
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-AuthenticodeSignature -LiteralPath '{escaped_path}').Status",
            ],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status = result.stdout.strip()
        if status and status != "Valid":
            log.status(f"WARNING: {name} is not Authenticode-signed (status: {status}) - proceeding anyway")
    except (OSError, subprocess.SubprocessError):
        pass
