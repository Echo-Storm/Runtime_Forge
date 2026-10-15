"""
Tests for installer integrity checks (SHA-256 / Authenticode publisher) and
the user-data directory split.

Run directly:
    venv\\Scripts\\python.exe tests\\test_integrity.py
"""

import http.server
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import downloader, paths, signature
from core.downloader import Trust, download, file_sha256, reverify
from core.logger import setup_logging
from core.version_resolvers import asset_sha256, _temurin_version_from_filename

tmp = Path(tempfile.mkdtemp(prefix="rf_integrity_"))
setup_logging(tmp)
results = {}

# ---- a tiny local web server serving one 20 KB "installer"
served = tmp / "served"
served.mkdir()
payload = os.urandom(20 * 1024)
(served / "setup.exe").write_bytes(payload)
good_sha = file_sha256(served / "setup.exe")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(served), **kw)

    def log_message(self, *a):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_address[1]}/setup.exe"

# ---- SHA-256
d1 = tmp / "d1"
d1.mkdir()
f = download(url, d1, "ok.exe", "ok", trust=Trust(sha256=good_sha))
results["matching_sha256_accepted"] = f is not None and f.is_file()

d2 = tmp / "d2"
d2.mkdir()
bad = download(url, d2, "bad.exe", "bad", trust=Trust(sha256="0" * 64))
results["wrong_sha256_rejected_and_file_removed"] = bad is None and not (d2 / "bad.exe").exists()

# a poisoned cache file must not be trusted just because it's big enough
d3 = tmp / "d3"
d3.mkdir()
(d3 / "cached.exe").write_bytes(os.urandom(20 * 1024))
c = download(url, d3, "cached.exe", "cached", trust=Trust(sha256=good_sha))
results["bad_cached_file_redownloaded"] = c is not None and file_sha256(c) == good_sha

# ---- re-verification at execution time
tamper = d1 / "ok.exe"
results["reverify_passes_untouched_file"] = reverify(tamper, "ok") is True
tamper.write_bytes(payload + b"x")
results["reverify_catches_swapped_file"] = reverify(tamper, "ok") is False
results["reverify_unknown_file_is_none"] = reverify(tmp / "never_downloaded.exe", "x") is None

# ---- Authenticode
d4 = tmp / "d4"
d4.mkdir()
unsigned = download(url, d4, "unsigned.exe", "unsigned", trust=Trust(publishers=("Microsoft Corporation",)))
results["unsigned_file_rejected_when_publisher_required"] = unsigned is None

info = signature.get_signature(str(tmp / "served" / "setup.exe"))
results["random_bytes_report_not_valid"] = not info.valid

signed = None
for cand in (Path(sys.base_prefix) / "python.exe",
             Path(os.environ.get("ProgramFiles", "")) / "PowerShell" / "7" / "pwsh.exe",
             Path(os.environ.get("ProgramFiles", "")) / "Git" / "cmd" / "git.exe",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"):
    if cand.is_file() and signature.get_signature(str(cand)).valid:
        signed = cand
        break
if signed is None:
    print("(no Authenticode-signed binary found on this machine - skipping the positive signature checks)")
else:
    sig = signature.get_signature(str(signed))
    results["signed_binary_valid_with_publisher_name"] = sig.valid and bool(sig.publisher)
    results["publisher_allowlist_accepts_real_signer"] = signature.publisher_matches(sig.publisher, [sig.publisher.split(" (")[0]])
    results["publisher_allowlist_rejects_other_signer"] = not signature.publisher_matches(sig.publisher, ["Definitely Not The Signer"])
    # tampering invalidates the signature: append a byte to a copy
    copy = tmp / "tampered.exe"
    shutil.copyfile(signed, copy)
    results["copy_still_valid"] = signature.get_signature(str(copy)).valid
    with open(copy, "ab") as fh:
        fh.write(b"\0" * 16)
    results["tampered_signed_binary_not_valid"] = not signature.get_signature(str(copy)).valid

# ---- API digest parsing / Temurin version parsing
results["asset_digest_parsed"] = asset_sha256({"digest": "sha256:abc123"}) == "abc123"
results["asset_digest_missing_is_none"] = asset_sha256({}) is None and asset_sha256({"digest": None}) is None
results["temurin_21_version"] = _temurin_version_from_filename("OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.msi") == "21.0.12.1+1"
results["temurin_17_version"] = _temurin_version_from_filename("OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.msi") == "17.0.20.1+1"
results["temurin_8_version"] = _temurin_version_from_filename("OpenJDK8U-jdk_x64_windows_hotspot_8u504b01.msi") == "8.0.504+1"

# ---- user-data directory
results["source_mode_data_dir_is_app_dir"] = paths.get_data_dir() == paths.get_app_dir()

fake_app = tmp / "ProgramFilesApp"
fake_app.mkdir()
(fake_app / "profiles").mkdir()
(fake_app / "profiles" / "mine.json").write_text("{}")
(fake_app / "RuntimeForge.ini").write_text("[General]\n")
local = tmp / "Local"
local.mkdir()

real_app_dir, real_frozen = paths.get_app_dir, getattr(sys, "frozen", None)
old_local = os.environ.get("LOCALAPPDATA")
try:
    paths.get_app_dir = lambda: fake_app
    sys.frozen = True
    os.environ["LOCALAPPDATA"] = str(local)
    data = paths.get_data_dir()
    results["frozen_data_dir_is_localappdata"] = data == local / "RuntimeForge"
    results["legacy_profiles_migrated"] = (data / "profiles" / "mine.json").is_file() and not (fake_app / "profiles").exists()
    results["legacy_ini_migrated"] = (data / "RuntimeForge.ini").is_file()

    # never overwrite what's already there
    (fake_app / "RuntimeForge.ini").write_text("[Old]\n")
    (data / "RuntimeForge.ini").write_text("[New]\n")
    paths.get_data_dir()
    results["migration_does_not_overwrite"] = (data / "RuntimeForge.ini").read_text() == "[New]\n"

    (fake_app / paths.PORTABLE_MARKER).write_text("")
    results["portable_marker_keeps_data_next_to_exe"] = paths.get_data_dir() == fake_app
finally:
    paths.get_app_dir = real_app_dir
    if real_frozen is None:
        del sys.frozen
    else:
        sys.frozen = real_frozen
    if old_local is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = old_local

server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)

for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
