"""
CLI diagnostic: prints a DLL/EXE's PE VERSIONINFO string fields.

This is what caught the OpenAL false-positive during development — an
NVIDIA-bundled OpenAL32.dll passed the old "does the file exist" check, and
this tool is what showed its real identity (ProductName "Standard OpenAL(TM)
Library" instead of "OpenAL Soft"). Keep it around for the next time a
component's presence check needs to tell two same-named binaries apart —
run it against the real file on a real machine before guessing at a fix.

Usage:
    python tools/inspect_dll_version.py <path> [field ...]
    python tools/inspect_dll_version.py C:\\Windows\\System32\\OpenAL32.dll
    python tools/inspect_dll_version.py some.dll ProductName ProductVersion
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.checks import dll_version_field

DEFAULT_FIELDS = ["ProductName", "ProductVersion", "FileDescription", "FileVersion", "CompanyName", "LegalCopyright"]


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    fields = sys.argv[2:] or DEFAULT_FIELDS

    print(path)
    for field in fields:
        print(f"  {field}: {dll_version_field(path, field)}")


if __name__ == "__main__":
    main()
