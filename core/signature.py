"""
Authenticode verification via WinVerifyTrust (no PowerShell round-trip), plus
the signer's display name so a component can pin *who* must have signed its
installer, not just that some valid signature exists.

check_signature() is the old warn-only entry point (still used for files
that didn't come through the downloader, e.g. DXSETUP.exe extracted from an
already-verified archive). verify_signature() is the strict one the
downloader uses.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional, Sequence

from core.logger import get_logger

_wintrust = ctypes.WinDLL("wintrust.dll")
_crypt32 = ctypes.WinDLL("crypt32.dll")

_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_REVOCATION_CHECK_NONE = 0x10
_CERT_NAME_SIMPLE_DISPLAY_TYPE = 4
_CERT_NAME_ATTR_TYPE = 3
_OID_ORGANIZATION_NAME = b"2.5.4.10"

TRUST_E_NOSIGNATURE = 0x800B0100
TRUST_E_PROVIDER_UNKNOWN = 0x800B0001
TRUST_E_SUBJECT_FORM_UNKNOWN = 0x800B0003
CRYPT_E_FILE_ERROR = 0x80092003


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


# WINTRUST_ACTION_GENERIC_VERIFY_V2
_ACTION_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B, 0xCD44, 0x11D0,
    (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
)


class _WinTrustFileInfo(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.c_void_p)]


class _WinTrustData(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
        ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
        ("pFile", ctypes.POINTER(_WinTrustFileInfo)), ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
        ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", ctypes.c_void_p),
    ]


class _CryptProviderCert(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pCert", ctypes.c_void_p)]


_wintrust.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.c_void_p]
_wintrust.WinVerifyTrust.restype = ctypes.c_long
_wintrust.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
_wintrust.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
_wintrust.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_wintrust.WTHelperGetProvSignerFromChain.restype = ctypes.c_void_p
_wintrust.WTHelperGetProvCertFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_wintrust.WTHelperGetProvCertFromChain.restype = ctypes.POINTER(_CryptProviderCert)
_crypt32.CertGetNameStringW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
_crypt32.CertGetNameStringW.restype = wintypes.DWORD


@dataclass
class SignatureInfo:
    valid: bool
    status: str                    # "Valid", "NotSigned", or "Invalid (0x...)"
    publisher: Optional[str] = None


def get_signature(path: str) -> SignatureInfo:
    """Authenticode status + signer name for an exe/msi/dll. Revocation
    checking is off (a network round-trip per file, and it fails offline);
    chain trust, timestamp and hash integrity are still verified."""
    file_info = _WinTrustFileInfo(ctypes.sizeof(_WinTrustFileInfo), path, None, None)
    data = _WinTrustData()
    data.cbStruct = ctypes.sizeof(_WinTrustData)
    data.dwUIChoice = _WTD_UI_NONE
    data.fdwRevocationChecks = _WTD_REVOKE_NONE
    data.dwUnionChoice = _WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file_info)
    data.dwStateAction = _WTD_STATEACTION_VERIFY
    data.dwProvFlags = _WTD_REVOCATION_CHECK_NONE

    result = _wintrust.WinVerifyTrust(None, ctypes.byref(_ACTION_GENERIC_VERIFY_V2), ctypes.byref(data))
    code = result & 0xFFFFFFFF
    publisher = None
    try:
        if code == 0 or code not in (TRUST_E_NOSIGNATURE, TRUST_E_PROVIDER_UNKNOWN,
                                      TRUST_E_SUBJECT_FORM_UNKNOWN, CRYPT_E_FILE_ERROR):
            publisher = _signer_name(data.hWVTStateData)
    finally:
        data.dwStateAction = _WTD_STATEACTION_CLOSE
        _wintrust.WinVerifyTrust(None, ctypes.byref(_ACTION_GENERIC_VERIFY_V2), ctypes.byref(data))

    if code == 0:
        return SignatureInfo(True, "Valid", publisher)
    if code == TRUST_E_NOSIGNATURE:
        return SignatureInfo(False, "NotSigned")
    return SignatureInfo(False, f"Invalid (0x{code:08X})", publisher)


def _signer_name(state_handle) -> Optional[str]:
    if not state_handle:
        return None
    prov = _wintrust.WTHelperProvDataFromStateData(state_handle)
    if not prov:
        return None
    signer = _wintrust.WTHelperGetProvSignerFromChain(prov, 0, False, 0)
    if not signer:
        return None
    cert = _wintrust.WTHelperGetProvCertFromChain(signer, 0)
    if not cert or not cert.contents.pCert:
        return None
    pcert = cert.contents.pCert
    buf = ctypes.create_unicode_buffer(256)
    cn = buf.value if _crypt32.CertGetNameStringW(pcert, _CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None, buf, 256) else ""
    # Some publishers put the real company in O= and a product name in CN=
    # (Microsoft's .NET installers are CN=".NET", O="Microsoft Corporation"),
    # so report both and let the allowlist match either.
    oid = ctypes.c_char_p(_OID_ORGANIZATION_NAME)
    obuf = ctypes.create_unicode_buffer(256)
    org = obuf.value if _crypt32.CertGetNameStringW(pcert, _CERT_NAME_ATTR_TYPE, 0, oid, obuf, 256) else ""
    if cn and org and org.lower() != cn.lower():
        return f"{cn} ({org})"
    return cn or org or None


def publisher_matches(actual: Optional[str], allowed: Sequence[str]) -> bool:
    if not actual:
        return False
    a = actual.lower()
    return any(p.lower() in a for p in allowed)


def verify_signature(path: str, name: str, publishers: Sequence[str]) -> bool:
    """Strict: True only if the file carries a valid Authenticode signature
    from one of `publishers`. Logs the reason on failure."""
    log = get_logger()
    info = get_signature(path)
    if not info.valid:
        log.fail(f"{name}: signature check failed ({info.status}) - refusing to run it")
        return False
    if not publisher_matches(info.publisher, publishers):
        log.fail(f"{name}: signed by '{info.publisher}', expected one of {list(publishers)} - refusing to run it")
        return False
    log.status(f"Signature OK: {name} (signed by {info.publisher})")
    return True


def check_signature(path: str, name: str) -> None:
    """Warn-only (files not downloaded through core.downloader)."""
    log = get_logger()
    try:
        info = get_signature(path)
    except OSError:
        return
    if not info.valid:
        log.status(f"WARNING: {name} is not validly Authenticode-signed (status: {info.status}) - proceeding anyway")
