"""Раздел «Секреты»: чтение статуса и запись .env на временных файлах (без реальных секретов)."""
import logging

import pytest

from desktop.core import envfile as E

FAKE = "fake-value-123"


def write(tmp_path, text, bom=False):
    p = tmp_path / ".env"
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return str(p)


def test_status_only_booleans(tmp_path):
    p = write(tmp_path, "# комментарий\nWS_TOKEN=abc\nYANDEX_MUSIC_TOKEN=\nDEVICE_ID=pc\n")
    assert E.status(p) == {"WS_TOKEN": True, "YANDEX_MUSIC_TOKEN": False}
    assert E.status(None) == {"WS_TOKEN": False, "YANDEX_MUSIC_TOKEN": False}
    assert "abc" not in repr(E.status(p))


def test_set_replaces_keeps_comments_order_and_crlf(tmp_path):
    p = write(tmp_path, "# Сакура\r\nDEVICE_ID=pc\r\nYANDEX_MUSIC_TOKEN=old\r\n\r\n# конец\r\nOTHER=1\r\n")
    E.set_secret(p, "YANDEX_MUSIC_TOKEN", FAKE)
    raw = open(p, "rb").read()
    assert raw == f"# Сакура\r\nDEVICE_ID=pc\r\nYANDEX_MUSIC_TOKEN={FAKE}\r\n\r\n# конец\r\nOTHER=1\r\n".encode()
    assert open(p + ".bak", "rb").read().endswith(b"OTHER=1\r\n") and b"old" in open(p + ".bak", "rb").read()


def test_set_appends_when_missing_and_writes_utf8_without_bom(tmp_path):
    p = write(tmp_path, "DEVICE_ID=pc", bom=True)
    E.set_secret(p, "WS_TOKEN", FAKE)
    raw = open(p, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode() == f"DEVICE_ID=pc\nWS_TOKEN={FAKE}\n"
    assert E.status(p)["WS_TOKEN"] is True


def test_duplicates_collapse_and_export_prefix(tmp_path):
    p = write(tmp_path, "export WS_TOKEN=a\nX=1\nWS_TOKEN=b\n")
    E.set_secret(p, "WS_TOKEN", FAKE)
    assert open(p, encoding="utf-8").read() == f"WS_TOKEN={FAKE}\nX=1\n"


@pytest.mark.parametrize("key,value", [("DEVICE_ID", "x"), ("WS_TOKEN", ""), ("WS_TOKEN", "a\nB=1"),
                                       ("WS_TOKEN", "x" * 5000)])
def test_rejects_bad_input_without_leaking_value(tmp_path, key, value):
    p = write(tmp_path, "WS_TOKEN=keep\n")
    with pytest.raises(E.SecretError) as e:
        E.set_secret(p, key, value)
    assert value.strip() == "" or value[:5] not in str(e.value)
    assert open(p, encoding="utf-8").read() == "WS_TOKEN=keep\n"


def test_backup_restricted_and_value_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    p = write(tmp_path, "WS_TOKEN=old\n")
    restricted = []
    E.set_secret(p, "WS_TOKEN", FAKE, restrict=restricted.append)
    assert restricted == [p + ".bak", p]
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "WS_TOKEN" in text and FAKE not in text and "old" not in text


def test_api_secrets_status_and_set(tmp_path, monkeypatch):
    import asyncio

    from desktop.core.api.server import ApiError
    from desktop.core.service import CoreService
    p = write(tmp_path, "WS_TOKEN=x\n")
    monkeypatch.setenv("SAKURA_ENV_FILE", p)
    svc = CoreService.__new__(CoreService)
    svc._restrict = lambda path: None
    st = asyncio.run(svc.cmd_secrets_status({}))
    assert st["keys"] == {"WS_TOKEN": True, "YANDEX_MUSIC_TOKEN": False} and st["exists"] is True
    out = asyncio.run(svc.cmd_secrets_set({"key": "YANDEX_MUSIC_TOKEN", "value": FAKE}))
    assert out == {"keys": {"WS_TOKEN": True, "YANDEX_MUSIC_TOKEN": True}, "restart_suggested": True}
    assert FAKE not in repr(out)
    with pytest.raises(ApiError) as e:
        asyncio.run(svc.cmd_secrets_set({"key": "DEVICE_ID", "value": "z"}))
    assert e.value.code == "bad_request"


def test_config_keys_validated_and_readable(tmp_path):
    p = write(tmp_path, "WS_TOKEN=x\nDEVICE_ID=mostech\n")
    E.set_secret(p, "VPS_WS_URL", "ws://31.76.80.5:8765")
    E.set_secret(p, "SERVER_TRANSPORT", "noise")
    assert E.config_values(p) == {"DEVICE_ID": "mostech",
                                  "VPS_WS_URL": "ws://31.76.80.5:8765", "SERVER_TRANSPORT": "noise"}
    for key, bad in (("VPS_WS_URL", "http://x"), ("SERVER_TRANSPORT", "tls"), ("DEVICE_ID", "мой пк!")):
        with pytest.raises(E.SecretError):
            E.set_secret(p, key, bad)
    assert "x" not in json_dump(E.config_values(p))  # секретов среди значений нет


def json_dump(d):
    import json
    return json.dumps(d)
