"""securechannel: команды Telegram /pair, /devices, /revoke.

Run: python -m pytest tests/test_securechannel_telegram.py -q
"""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config
import modules.state as st
from adapters.commands import cmd_devices_impl, cmd_pair_impl, cmd_revoke_impl
from sakura_core import secure_policy
from securechannel.handshake import generate_keypair
from securechannel.pairing import words_to_psk

pytest.importorskip("noise")


def msg(text):
    return SimpleNamespace(text=text, answer=AsyncMock(), answer_photo=AsyncMock())


def test_pair_off_mode_refuses(monkeypatch):
    monkeypatch.setattr(config, "SECURE_CHANNEL", "off")
    m = msg("/pair")
    asyncio.run(cmd_pair_impl(m))
    assert "выключен" in m.answer.await_args.args[0]
    m.answer_photo.assert_not_awaited()


def test_pair_sends_qr_and_words(monkeypatch, caplog):
    monkeypatch.setattr(config, "SECURE_CHANNEL", "optional")
    m = msg("/pair")
    asyncio.run(cmd_pair_impl(m))
    photo, = m.answer_photo.await_args.args
    caption = m.answer_photo.await_args.kwargs["caption"]
    assert photo.data[:8] == b"\x89PNG\r\n\x1a\n"
    words = re.search(r"<code>([а-я ]+)</code>", caption).group(1)
    assert len(words.split()) == 8
    ctx = secure_policy.context()
    assert ctx.pairing.active_psk() == words_to_psk(words)
    assert "Отпечаток ключа сервера" in caption
    assert words not in caplog.text, "слова не журналируются"


def test_devices_and_revoke_closes_connection(monkeypatch):
    monkeypatch.setattr(config, "SECURE_CHANNEL", "optional")
    reg = secure_policy.context().registry
    reg.add(generate_keypair()[1], name="Ноутбук", id_hint="mostech")
    m = msg("/devices")
    asyncio.run(cmd_devices_impl(m))
    assert "mostech" in m.answer.await_args.args[0] and "не в сети" in m.answer.await_args.args[0]

    closed = {}

    class Conn:
        transport = "noise"

        async def close(self, code, reason=""):
            closed["code"] = code
    monkeypatch.setitem(st.connected_devices, "mostech", Conn())
    m = msg("/revoke mostech")
    asyncio.run(cmd_revoke_impl(m))
    assert "отозван" in m.answer.await_args.args[0] and closed == {"code": 4408}
    assert reg.get("mostech")["revoked"]
    for text in ("/revoke", "/revoke mostech"):
        m = msg(text)
        asyncio.run(cmd_revoke_impl(m))
        assert "/revoke" in m.answer.await_args.args[0] or "не найдено" in m.answer.await_args.args[0]


def test_devices_empty(monkeypatch):
    m = msg("/devices")
    asyncio.run(cmd_devices_impl(m))
    assert "нет" in m.answer.await_args.args[0]
