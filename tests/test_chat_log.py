"""feat/proto-v2: хранилище журнала чата (modules/chat_log.py).

База — своя на каждый тест (conftest.isolated_chat_log).

Run: python -m pytest tests/test_chat_log.py -q
"""

import json
import os
import sqlite3
import stat
import time

import pytest

import config
from modules import chat_log


def _add(text, role="user", channel="voice", device="laptop", **kw):
    return chat_log.append(role, channel, text, device=device, **kw)[0]


def test_file_is_private_and_wal():
    _add("привет")
    path = config.CHAT_DB_PATH
    for p in (path, path + "-wal", path + "-shm"):
        if os.path.exists(p):
            assert stat.S_IMODE(os.stat(p).st_mode) == 0o600, p
    mode = sqlite3.connect(path).execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_append_fields_and_wire_shape():
    m = _add("Включи музыку", channel="text", client_msg_id="c1",
             meta={"turn_id": "abc123def456", "token": "секрет", "text": "дубль"})
    assert m["role"] == "user" and m["channel"] == "text" and m["device"] == "laptop"
    assert m["meta"] == {"turn_id": "abc123def456"}, "в meta только разрешённые ключи"
    w = chat_log.to_wire(m)
    assert w == {"id": str(m["id"]), "ts": m["ts"], "role": "user",
                 "text": "Включи музыку", "channel": "text", "device": "laptop",
                 "client_msg_id": "c1", "turn_id": "abc123def456"}
    assert isinstance(w["ts"], float)


@pytest.mark.parametrize("role,channel", [("bot", "voice"), ("user", "sms")])
def test_rejects_unknown_role_and_channel(role, channel):
    with pytest.raises(ValueError):
        chat_log.append(role, channel, "x")


def test_rejects_empty_text():
    with pytest.raises(ValueError):
        chat_log.append("user", "voice", "   ")


def test_client_msg_id_dedup_per_device():
    a, created_a = chat_log.append("user", "text", "раз", device="laptop", client_msg_id="c1")
    b, created_b = chat_log.append("user", "text", "раз", device="laptop", client_msg_id="c1")
    c, created_c = chat_log.append("user", "text", "раз", device="pc", client_msg_id="c1")
    assert created_a and not created_b and created_c
    assert a["id"] == b["id"] != c["id"]
    assert chat_log.count() == 2


def test_history_pages_ascending_with_has_more():
    ids = [_add(f"сообщение {i}")["id"] for i in range(7)]
    page, more = chat_log.history(limit=3)
    assert [m["id"] for m in page] == ids[4:] and more
    page, more = chat_log.history(before_id=ids[4], limit=3)
    assert [m["id"] for m in page] == ids[1:4] and more
    page, more = chat_log.history(before_id=ids[1], limit=3)
    assert [m["id"] for m in page] == ids[:1] and not more


def test_history_before_ts_and_limit_cap():
    for i in range(120):
        chat_log.append("user", "voice", f"m{i}", ts=1000.0 + i)
    page, more = chat_log.history(limit=1000)
    assert len(page) == chat_log.HISTORY_MAX == 100 and more
    page, _ = chat_log.history(before_ts=1005.0, limit=50)
    assert [m["text"] for m in page] == [f"m{i}" for i in range(5)]


def test_search_prefix_cyrillic_and_safe_syntax():
    _add("Включи музыку погромче")
    _add("Какая погода завтра?")
    _add("МУЗЫКА играет")
    found = chat_log.search("музык")
    assert [m["text"] for m in found] == ["МУЗЫКА играет", "Включи музыку погромче"]
    # синтаксис FTS5 из ввода не исполняется: кавычки/звёздочки — просто разделители,
    # OR/NEAR — обычные слова (все слова запроса должны встретиться)
    assert [m["text"] for m in chat_log.search('погод"*')] == ["Какая погода завтра?"]
    assert chat_log.search("погода OR музыку") == []
    assert chat_log.search("NEAR(") == []
    assert chat_log.search("   ") == []


def test_delete_and_clear_keep_fts_consistent():
    a = _add("первое слово")
    _add("второе слово")
    assert chat_log.delete(a["id"]) and not chat_log.delete(a["id"])
    assert [m["text"] for m in chat_log.search("слово")] == ["второе слово"]
    chat_log.mark_read("laptop", chat_log.last_id())
    assert chat_log.clear() == 1
    assert chat_log.count() == 0 and chat_log.search("слово") == []
    assert chat_log.get_read("laptop") == 0
    # id после очистки не переиспользуются (AUTOINCREMENT)
    assert _add("новое")["id"] > a["id"]


def test_mark_read_forward_only_and_clamped():
    ids = [_add(f"m{i}")["id"] for i in range(3)]
    assert chat_log.mark_read("laptop", ids[1]) == ids[1]
    assert chat_log.mark_read("laptop", ids[0]) == ids[1]       # назад — нет
    assert chat_log.mark_read("laptop", 10**9) == ids[2]        # не дальше последнего
    assert chat_log.get_read("pc") == 0


def test_pause_flag_and_env_force(monkeypatch):
    assert not chat_log.is_paused()
    chat_log.set_paused(True)
    assert chat_log.is_paused()
    chat_log.set_paused(False)
    assert not chat_log.is_paused()
    monkeypatch.setattr(config, "CHAT_LOG_PAUSED", True)
    assert chat_log.is_paused()


def test_retention(monkeypatch):
    now = time.time()
    chat_log.append("user", "voice", "старое", ts=now - 10 * 86400)
    chat_log.append("user", "voice", "свежее", ts=now - 3600)
    assert chat_log.purge_old(0) == 0                   # 0 — бессрочно
    assert chat_log.purge_old(7) == 1
    assert [m["text"] for m in chat_log.history()[0]] == ["свежее"]
    assert chat_log.search("старое") == []


def test_export_md_and_json():
    _add("Привет", device="laptop")
    _add("Привет, Мастер.", role="assistant")
    md = chat_log.export("md")
    assert "Мастер** (voice, laptop): Привет" in md
    assert "Сакура** (voice, laptop): Привет, Мастер." in md
    data = json.loads(chat_log.export("json"))
    assert [m["role"] for m in data] == ["user", "assistant"]


def test_parse_id():
    assert chat_log.parse_id(5) == 5
    assert chat_log.parse_id("5") == 5
    assert chat_log.parse_id("m5") == 5
    for bad in (None, True, "x", "", "m", "-1", 1.5):
        assert chat_log.parse_id(bad) is None, bad


def test_stats_reports_size():
    _add("x" * 1000)
    s = chat_log.stats()
    assert s["messages"] == 1 and s["bytes"] > 0
