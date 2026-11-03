"""core.secure_store: формат, права, атомарность, DPAPI-обёртка, ротация (ТЗ-4)."""

import base64
import json
import os
import subprocess
import sys

import pytest
from core import secure_store, transport
from core.secure_store import DeviceKeys, SecureStore, StoreError

transport._ensure_securechannel_path()
from securechannel.handshake import generate_keypair
from securechannel.keys import fingerprint

b64 = lambda b: base64.b64encode(b).decode()


def _keys(server_pub=None):
    priv, pub = generate_keypair()
    spub = server_pub or generate_keypair()[1]
    return DeviceKeys(device_id="mostech", priv=b64(priv), pub=b64(pub),
                      server_url="ws://127.0.0.1:1", server_pub=b64(spub),
                      server_fp=fingerprint(spub), paired_at=1.0)


def _xor(data: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in data)


def test_roundtrip_plain(tmp_path):
    st = SecureStore(str(tmp_path / "secure"), use_dpapi=False)
    assert st.load() is None
    k = _keys()
    st.save(k)
    assert st.load() == k
    raw = json.loads((tmp_path / "secure" / "device.json").read_text(encoding="utf-8"))
    assert raw["v"] == 1 and raw["priv"] == k.priv and "priv_dpapi" not in raw


@pytest.mark.skipif(os.name == "nt", reason="права POSIX")
def test_permissions_posix(tmp_path):
    d = tmp_path / "secure"
    SecureStore(str(d), use_dpapi=False).save(_keys())
    assert d.stat().st_mode & 0o777 == 0o700
    assert (d / "device.json").stat().st_mode & 0o777 == 0o600
    assert [p.name for p in d.iterdir()] == ["device.json"]      # без временных файлов


def test_dpapi_wraps_private_key(tmp_path):
    st = SecureStore(str(tmp_path), protect=_xor, unprotect=_xor)
    k = _keys()
    st.save(k)
    text = (tmp_path / "device.json").read_text(encoding="utf-8")
    raw = json.loads(text)
    assert "priv" not in raw and k.priv not in text
    assert base64.b64decode(raw["priv_dpapi"]) == _xor(base64.b64decode(k.priv))
    assert st.load().priv == k.priv
    # тот же файл без DPAPI не читается молча
    with pytest.raises(StoreError):
        SecureStore(str(tmp_path), use_dpapi=False).load()


def test_restrict_before_secret_written(tmp_path):
    seen = []

    def restrict(path, folder=False):
        seen.append((os.path.basename(path), folder,
                     None if folder else os.path.getsize(path)))

    SecureStore(str(tmp_path / "s"), use_dpapi=False, restrict_fn=restrict).save(_keys())
    assert seen[0] == ("s", True, None)
    name, folder, size = seen[1]
    assert name.startswith(".tmp-") and folder is False and size == 0


def test_failed_restrict_keeps_previous_file(tmp_path):
    good = SecureStore(str(tmp_path), use_dpapi=False)
    old = _keys()
    good.save(old)

    def deny(path, folder=False):
        raise OSError("icacls failed")

    with pytest.raises(OSError):
        SecureStore(str(tmp_path), use_dpapi=False, restrict_fn=deny).save(_keys())
    assert good.load() == old
    assert sorted(p.name for p in tmp_path.iterdir()) == ["device.json"]


def test_icacls_command(monkeypatch):
    calls = []
    monkeypatch.setenv("USERNAME", "master")
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: calls.append(args))
    secure_store._icacls(r"C:\x\device.json", folder=False)
    secure_store._icacls(r"C:\x", folder=True)
    assert calls == [["icacls", r"C:\x\device.json", "/inheritance:r", "/grant:r", "master:F"],
                     ["icacls", r"C:\x", "/inheritance:r", "/grant:r", "master:(OI)(CI)F"]]


def test_restrict_on_windows_uses_icacls(monkeypatch):
    monkeypatch.setattr(secure_store.os, "name", "nt")
    got = []
    monkeypatch.setattr(secure_store, "_icacls", lambda p, folder: got.append((p, folder)))
    secure_store.restrict("f", folder=False)
    assert got == [("f", False)]


def test_rotation_next_then_promote(tmp_path):
    st = SecureStore(str(tmp_path), use_dpapi=False)
    st.save(_keys())
    _, new_pub = generate_keypair()
    st.set_next_server_pub(b64(new_pub))
    assert st.load().next_server_pub == b64(new_pub)
    st.promote_next()
    k = st.load()
    assert k.server_pub == b64(new_pub) and k.server_fp == fingerprint(new_pub)
    assert k.next_server_pub is None


def test_corrupt_file_is_error_not_unpaired(tmp_path):
    (tmp_path / "device.json").write_text("{not json", encoding="utf-8")
    st = SecureStore(str(tmp_path), use_dpapi=False)
    with pytest.raises(StoreError):
        st.load()
    with pytest.raises(transport.SecureHandshakeFailed):
        transport.load_keys(st)


def test_wipe(tmp_path):
    st = SecureStore(str(tmp_path), use_dpapi=False)
    st.save(_keys())
    st.wipe()
    st.wipe()
    assert st.load() is None


def test_module_api_and_transport_default_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SAKURA_SECURE_DIR", str(tmp_path / "env"))
    monkeypatch.setattr(secure_store, "_dpapi", lambda: None)
    monkeypatch.setattr(secure_store, "_default", None)
    assert transport._default_store() is secure_store
    assert secure_store.load() is None
    k = _keys()
    secure_store.save(k)
    assert transport.load_keys() == k
    assert (tmp_path / "env" / "device.json").is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI только на Windows")
def test_real_dpapi_roundtrip(tmp_path):
    st = SecureStore(str(tmp_path))
    k = _keys()
    st.save(k)
    assert "priv_dpapi" in json.loads((tmp_path / "device.json").read_text("utf-8"))
    assert st.load() == k
