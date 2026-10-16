"""securechannel: криптоядро Noise — официальные векторы, сверка учебной
реализации с noiseprotocol, негативные случаи рукопожатий.

Run: python -m pytest tests/test_securechannel_noise.py -q
"""

import json
from pathlib import Path

import pytest

from securechannel.handshake import Handshake, HandshakeError, IntegrityError, generate_keypair
from securechannel.noise.core import (
    CipherState,
    HandshakeState,
    KeyPair,
    NoiseError,
    SymmetricState,
    hkdf,
)

pytest.importorskip("noise", reason="noiseprotocol (requirements.txt)")

VECTORS = json.loads((Path(__file__).resolve().parent.parent / "securechannel" / "vectors"
                      / "noise_vectors.json").read_text())
BACKENDS = ("edu", "lib")


def _hx(s):
    return bytes.fromhex(s)


def _sides(v, backend):
    pat = v["protocol_name"].split("_")[1]
    psk_i = _hx(v["init_psks"][0]) if "init_psks" in v else None
    psk_r = _hx(v["resp_psks"][0]) if "resp_psks" in v else None
    rs = _hx(v["init_remote_static"]) if "init_remote_static" in v else None
    i = Handshake(pat, True, _hx(v["init_static"]), rs_pub=rs, psk=psk_i,
                  prologue=_hx(v["init_prologue"]), backend=backend,
                  e_priv=_hx(v["init_ephemeral"]))
    r = Handshake(pat, False, _hx(v["resp_static"]), psk=psk_r,
                  prologue=_hx(v["resp_prologue"]), backend=backend,
                  e_priv=_hx(v["resp_ephemeral"]))
    return i, r


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: v["protocol_name"])
def test_official_vectors(v, backend):
    i, r = _sides(v, backend)
    ciphers = None
    for n, m in enumerate(v["messages"]):
        writer, reader = (i, r) if n % 2 == 0 else (r, i)
        payload = _hx(m["payload"])
        if not writer.complete:
            ct = writer.write(payload)
            pt = reader.read(ct)
        else:
            if ciphers is None:
                ciphers = {"i": i.split(), "r": r.split()}
            send = ciphers["i"][0] if n % 2 == 0 else ciphers["r"][0]
            recv = ciphers["r"][1] if n % 2 == 0 else ciphers["i"][1]
            ct = send.encrypt(payload)
            pt = recv.decrypt(ct)
        assert ct.hex() == m["ciphertext"], (backend, n)
        assert pt == payload
    assert i.handshake_hash.hex() == v["handshake_hash"]
    assert r.handshake_hash == i.handshake_hash


def test_vectors_file_has_source():
    assert "cacophony" in VECTORS["source"]
    names = {v["protocol_name"] for v in VECTORS["vectors"]}
    assert names == {"Noise_IK_25519_ChaChaPoly_BLAKE2s", "Noise_XXpsk3_25519_ChaChaPoly_BLAKE2s"}


# ── дифференциальные: учебная ≡ библиотека ────────────────────────

def _keys():
    return generate_keypair(), generate_keypair(), generate_keypair(), generate_keypair()


@pytest.mark.parametrize("pattern", ["IK", "XXpsk3"])
def test_edu_equals_lib_bytes(pattern):
    """Одинаковые входы (включая эфемерные ключи) → одинаковые байты."""
    (ip, ipub), (rp, rpub), (iep, _), (rep, _) = _keys()
    psk = bytes(range(32))
    out = {}
    for backend in BACKENDS:
        kw_i = dict(e_priv=iep, backend=backend)
        kw_r = dict(e_priv=rep, backend=backend)
        if pattern == "IK":
            i = Handshake.ik_initiator(ip, rpub, **kw_i)
            r = Handshake.ik_responder(rp, **kw_r)
        else:
            i = Handshake.xx_initiator(ip, psk, **kw_i)
            r = Handshake.xx_responder(rp, psk, **kw_r)
        msgs = []
        w, rd = i, r
        n = 0
        while not (i.complete and r.complete):
            ct = w.write(f"payload {n}".encode())
            assert rd.read(ct) == f"payload {n}".encode()
            msgs.append(ct)
            w, rd = rd, w
            n += 1
        (si, ri), (sr, rr) = i.split(), r.split()
        msgs += [si.encrypt(b"transport-1"), sr.encrypt(b"transport-2")]
        assert rr.decrypt(msgs[-2]) == b"transport-1" and ri.decrypt(msgs[-1]) == b"transport-2"
        out[backend] = (msgs, i.handshake_hash, i.remote_static, r.remote_static)
    assert out["edu"] == out["lib"]
    assert out["lib"][2] == rpub and out["lib"][3] == ipub


@pytest.mark.parametrize("ib,rb", [("edu", "lib"), ("lib", "edu")])
@pytest.mark.parametrize("pattern", ["IK", "XXpsk3"])
def test_cross_backend_handshake(pattern, ib, rb):
    (ip, _), (rp, rpub), _, _ = _keys()
    psk = b"\x07" * 32
    if pattern == "IK":
        i, r = Handshake.ik_initiator(ip, rpub, backend=ib), Handshake.ik_responder(rp, backend=rb)
    else:
        i, r = Handshake.xx_initiator(ip, psk, backend=ib), Handshake.xx_responder(rp, psk, backend=rb)
    w, rd = i, r
    while not (i.complete and r.complete):
        rd.read(w.write(b"x"))
        w, rd = rd, w
    (si, ri), (sr, rr) = i.split(), r.split()
    for k in range(5):
        assert rr.decrypt(si.encrypt(b"m%d" % k)) == b"m%d" % k
        si.rekey(), rr.rekey()
        assert ri.decrypt(sr.encrypt(b"n%d" % k)) == b"n%d" % k


# ── негативные рукопожатия ────────────────────────────────────────

@pytest.mark.parametrize("backend", BACKENDS)
def test_ik_wrong_server_key_fails(backend):
    (ip, _), (rp, _), (_, other_pub), _ = _keys()
    i = Handshake.ik_initiator(ip, other_pub, backend=backend)
    r = Handshake.ik_responder(rp, backend=backend)
    with pytest.raises(HandshakeError):
        r.read(i.write(b"id"))


@pytest.mark.parametrize("backend", BACKENDS)
def test_xx_wrong_psk_fails_at_message3(backend):
    (ip, _), (rp, _), _, _ = _keys()
    i = Handshake.xx_initiator(ip, b"\x01" * 32, backend=backend)
    r = Handshake.xx_responder(rp, b"\x02" * 32, backend=backend)
    r.read(i.write())
    i.read(r.write())
    with pytest.raises(HandshakeError):
        r.read(i.write(b"{}"))


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("pos", [0, 31, 32, 64, -17, -1])
def test_ik_bitflip_anywhere_fails(backend, pos):
    (ip, _), (rp, rpub), _, _ = _keys()
    m1 = bytearray(Handshake.ik_initiator(ip, rpub, backend=backend).write(b'{"v":1}'))
    m1[pos] ^= 0x01
    with pytest.raises(HandshakeError):
        Handshake.ik_responder(rp, backend=backend).read(bytes(m1))


@pytest.mark.parametrize("backend", BACKENDS)
def test_truncated_and_prologue_mismatch(backend):
    (ip, _), (rp, rpub), _, _ = _keys()
    m1 = Handshake.ik_initiator(ip, rpub, backend=backend).write(b"x")
    for cut in (0, 10, 32, len(m1) - 1):
        with pytest.raises(HandshakeError):
            Handshake.ik_responder(rp, backend=backend).read(m1[:cut])
    # XX-сообщение не годится для IK: другой пролог и паттерн
    xx = Handshake.xx_initiator(ip, b"\x00" * 32, backend=backend).write(b"")
    with pytest.raises(HandshakeError):
        Handshake.ik_responder(rp, backend=backend).read(xx)


@pytest.mark.parametrize("backend", BACKENDS)
def test_ik_init_replay_gives_attacker_nothing(backend):
    """Повтор IK_INIT: сервер отвечает, но без эфемерного ключа клиента
    ответ не расшифровать — повтор бесполезен (PROTOCOL.md §3.2)."""
    (ip, _), (rp, rpub), _, _ = _keys()
    client = Handshake.ik_initiator(ip, rpub, backend=backend)
    m1 = client.write(b'{"v":1,"device_id":"x"}')
    r1, r2 = Handshake.ik_responder(rp, backend=backend), Handshake.ik_responder(rp, backend=backend)
    r1.read(m1)
    r2.read(m1)                      # повтор принят на уровне рукопожатия…
    m2a, m2b = r1.write(b"a"), r2.write(b"b")
    assert m2a[:32] != m2b[:32]      # …но эфемерные ключи сервера разные
    client.read(m2a)                 # настоящий клиент — только свой ответ
    other = Handshake.ik_initiator(generate_keypair()[0], rpub, backend=backend)
    other.write(b"x")
    with pytest.raises(HandshakeError):
        other.read(m2b)              # атакующий не расшифрует


def test_transport_replay_reorder_and_tamper():
    (ip, _), (rp, rpub), _, _ = _keys()
    i, r = Handshake.ik_initiator(ip, rpub), Handshake.ik_responder(rp)
    r.read(i.write())
    i.read(r.write())
    (si, _), (_, rr) = i.split(), r.split()
    c0, c1, c2 = si.encrypt(b"0"), si.encrypt(b"1"), si.encrypt(b"2")
    assert rr.decrypt(c0) == b"0"
    with pytest.raises(IntegrityError):
        rr.decrypt(c0)               # повтор
    with pytest.raises(IntegrityError):
        rr.decrypt(c2)               # перестановка: 2 раньше 1
    assert rr.decrypt(c1) == b"1"    # неудача не сдвигает счётчик
    bad = bytearray(c2)
    bad[0] ^= 1
    with pytest.raises(IntegrityError):
        rr.decrypt(bytes(bad))       # подмена
    assert rr.decrypt(c2) == b"2"


def test_edu_internals_errors():
    cs = CipherState()
    assert cs.encrypt_with_ad(b"", b"plain") == b"plain"      # без ключа — как есть
    with pytest.raises(NoiseError):
        cs.rekey()
    cs = CipherState(b"\x00" * 32)
    cs.n = 2**64 - 1
    with pytest.raises(NoiseError):
        cs.encrypt_with_ad(b"", b"x")
    with pytest.raises(NoiseError):
        cs.decrypt_with_ad(b"", b"x" * 20)
    with pytest.raises(NoiseError):
        HandshakeState("NN", True)
    with pytest.raises(NoiseError):
        HandshakeState("XXpsk3", True, s=KeyPair.generate())
    with pytest.raises(NoiseError):
        HandshakeState("IK", True, s=KeyPair.generate())          # нет rs
    hs = HandshakeState("IK", False, s=KeyPair.generate())
    with pytest.raises(NoiseError):
        hs.write_message(b"")                                     # не наша очередь
    with pytest.raises(NoiseError):
        hs.split()
    with pytest.raises(NoiseError):
        KeyPair.generate().dh(b"\x00" * 32)                       # точка малого порядка
    long = SymmetricState(b"x" * 40)
    assert len(long.h) == 32
    assert len(hkdf(b"\x00" * 32, b"", 3)) == 3


def test_handshake_api_errors():
    (ip, _), (rp, rpub), _, _ = _keys()
    with pytest.raises(ValueError):
        Handshake.ik_responder(rp, backend="other")
    for backend in BACKENDS:
        r = Handshake.ik_responder(rp, backend=backend)
        with pytest.raises(HandshakeError):
            r.split()
        with pytest.raises(HandshakeError):
            r.write(b"")              # ответчик не начинает
        i = Handshake.ik_initiator(ip, rpub, backend=backend)
        i.write(b"")
        with pytest.raises(HandshakeError):
            i.write(b"")              # дважды подряд
