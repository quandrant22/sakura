"""Windows DPAPI: CryptProtectData / CryptUnprotectData — данные шифруются ключом текущего пользователя."""
import ctypes
import ctypes.wintypes as wt


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_ENTROPY = b"sakura-securechannel/1 device key"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _take(b: _Blob) -> bytes:
    try:
        return ctypes.string_at(b.pbData, b.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(b.pbData)


def protect(data: bytes) -> bytes:
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(_blob(data)), "sakura", ctypes.byref(_blob(_ENTROPY)),
                                                None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI: не удалось зашифровать")
    return _take(out)


def unprotect(blob: bytes) -> bytes:
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(_blob(blob)), None, ctypes.byref(_blob(_ENTROPY)),
                                                  None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI: не удалось расшифровать (другой пользователь или повреждено)")
    return _take(out)
