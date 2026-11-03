"""Спаривание агента против настоящего securechannel.server (ТЗ-4).

QR и слова; неверные слова; подмена ключа сервера при QR — обрыв до XX_3;
истёкший QR; после спаривания — вход по Noise; секреты не в журнале.
"""

import dataclasses
import sys
import time
from pathlib import Path

import pytest
from core import pairing, transport
from core.secure_store import SecureStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from noise_test_server import Server, recv_json, run

from securechannel.handshake import generate_keypair
from securechannel.keys import fingerprint
from securechannel.pairing import make_qr_uri


def _store(tmp_path):
    return SecureStore(str(tmp_path / "dev"), use_dpapi=False)


def _qr(srv, words, expires, server_pub=None):
    return make_qr_uri(srv.url, server_pub or srv.ctx.keys.current[1], words, expires)


def test_pair_by_qr_then_noise(tmp_path, caplog):
    store = _store(tmp_path)

    async def go():
        async with Server(tmp_path) as srv:
            words, expires = srv.ctx.pairing.create()
            qr = _qr(srv, words, expires)
            with caplog.at_level("DEBUG"):
                res = await pairing.pair_device(qr, server_url=srv.url, store=store,
                                                device_id_hint="mostech")
            assert res.mode == "qr"
            assert res.server_fp == fingerprint(srv.ctx.keys.current[1])
            assert srv.ctx.pairing.active_psk() is None          # код израсходован
            conn = await transport.open_connection(srv.url, "prefer", store=store)
            assert conn.secure and conn.device_id == res.device_id
            await conn.send_json({"type": "register", "token": "не уйдёт"})
            assert (await recv_json(conn))["msg"] == {"type": "register"}
            await conn.close()
            return words, qr

    words, qr = run(go)
    keys = store.load()
    assert keys.server_fp and keys.priv
    for secret in (qr, words, keys.priv, *words.split()):
        assert secret not in caplog.text


def test_pair_by_words(tmp_path):
    store = _store(tmp_path)

    async def go():
        async with Server(tmp_path) as srv:
            words, _ = srv.ctx.pairing.create()
            res = await pairing.pair_device(words.upper().replace(" ", ",  "),
                                            server_url=srv.url, store=store)
            assert res.mode == "words"
            assert "сверьте отпечаток" in pairing.describe(res)
            assert len(srv.ctx.registry.list()) == 1

    run(go)
    assert store.load() is not None


def test_wrong_words_keep_previous_keys(tmp_path):
    store = _store(tmp_path)

    async def go():
        async with Server(tmp_path) as srv:
            srv.ctx.pairing.create()
            first = srv.pair()                       # уже спарено ранее
            store.save(first.keys)
            other = " ".join([pairing_words()[0]] * 8)
            with pytest.raises(pairing.PairingError):
                await pairing.pair_device(other, server_url=srv.url, store=store,
                                          timeout=3)
            return first.keys

    before = run(go)
    assert dataclasses.asdict(store.load()) == dataclasses.asdict(before)


def pairing_words():
    from securechannel.pairing import WORDLIST
    return WORDLIST


def test_qr_with_substituted_server_key_aborts_before_xx3(tmp_path):
    store = _store(tmp_path)

    async def go():
        async with Server(tmp_path) as srv:
            words, expires = srv.ctx.pairing.create()
            _, fake_pub = generate_keypair()
            qr = _qr(srv, words, expires, server_pub=fake_pub)
            with pytest.raises(pairing.PairingError, match="подмена"):
                await pairing.pair_device(qr, server_url=srv.url, store=store)
            assert srv.ctx.registry.list() == []             # XX_3 не ушёл
            assert srv.ctx.pairing.status()["used"] is False

    run(go)
    assert store.load() is None


def test_expired_qr_does_not_connect(tmp_path):
    store = _store(tmp_path)
    _, pub = generate_keypair()
    words = " ".join(pairing_words()[:8])
    qr = make_qr_uri("ws://127.0.0.1:1", pub, words, time.time() - 1)

    def connect(*a, **k):
        raise AssertionError("не должен подключаться")

    with pytest.raises(pairing.PairingError, match="истёк"):
        run(lambda: pairing.pair_device(qr, store=store, connect=connect))
    assert store.load() is None


@pytest.mark.parametrize("text,msg", [("", "не введён"), ("один два", "нужно 8"),
                                      ("sakura-pair://1?x=1", "не распознана"),
                                      ("абв " * 8, "неизвестных")])
def test_parse_code_errors(text, msg):
    with pytest.raises(pairing.PairingError, match=msg):
        pairing.parse_code(text)


def test_unreachable_server(tmp_path):
    words = " ".join(pairing_words()[:8])
    with pytest.raises(pairing.PairingError, match="недоступен"):
        run(lambda: pairing.pair_device(words, server_url="ws://127.0.0.1:9",
                                        store=_store(tmp_path), timeout=2))
