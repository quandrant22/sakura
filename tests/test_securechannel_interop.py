"""securechannel: интероп-векторы (securechannel/vectors/interop.json) —
детерминированные транскрипты IK и XXpsk3 с транспортом и rekey, через оба
движка (lib, edu) и их смеси. Векторы: scripts/gen_interop_vectors.py.

Run: python -m pytest tests/test_securechannel_interop.py -q
"""

import importlib.util
import json
from pathlib import Path

import pytest

from securechannel.channel import SecureChannel
from securechannel.frames import FrameType, InnerType, encode_frame
from securechannel.handshake import (
    PROLOGUE_PAIR,
    PROLOGUE_SESSION,
    Handshake,
    IntegrityError,
    public_key,
)
from securechannel.keys import b64url
from securechannel.pairing import words_to_psk

pytest.importorskip("noise", reason="noiseprotocol (requirements.txt)")
pytestmark = pytest.mark.filterwarnings("ignore:One of ephemeral keypairs")

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "securechannel" / "vectors" / "interop.json").read_text("utf-8"))
TRANSCRIPTS = {t["name"]: t for t in VECTORS["transcripts"]}
BACKENDS = ("lib", "edu")
PAIRS = [(i, r) for i in BACKENDS for r in BACKENDS]
OTHER = {"initiator": "responder", "responder": "initiator"}


def _hx(s):
    return bytes.fromhex(s)


def _handshakes(t, ib, rb):
    if t["pattern"] == "IK":
        i = Handshake.ik_initiator(_hx(t["initiator_static"]), _hx(t["responder_static_pub"]),
                                   backend=ib, e_priv=_hx(t["initiator_ephemeral"]))
        r = Handshake.ik_responder(_hx(t["responder_static"]), backend=rb,
                                   e_priv=_hx(t["responder_ephemeral"]))
    else:
        psk = _hx(t["psk"])
        i = Handshake.xx_initiator(_hx(t["initiator_static"]), psk, backend=ib,
                                   e_priv=_hx(t["initiator_ephemeral"]))
        r = Handshake.xx_responder(_hx(t["responder_static"]), psk, backend=rb,
                                   e_priv=_hx(t["responder_ephemeral"]))
    return {"initiator": i, "responder": r}


def _channels(t, sides):
    return {who: SecureChannel(*hs.split(), rekey_messages=t["rekey_messages"],
                               clock=lambda: 0.0)
            for who, hs in sides.items()}


def _run_handshake(t, sides):
    for m in t["handshake"]:
        msg = sides[m["from"]].write(_hx(m["payload"]))
        assert msg.hex() == m["message"], m["frame_type"]
        assert encode_frame(FrameType[m["frame_type"]], msg).hex() == m["frame"]
        assert sides[OTHER[m["from"]]].read(msg) == _hx(m["payload"])
    i, r = sides["initiator"], sides["responder"]
    assert i.handshake_hash.hex() == t["handshake_hash"] == r.handshake_hash.hex()
    assert i.remote_static.hex() == t["responder_static_pub"]
    assert r.remote_static.hex() == t["initiator_static_pub"]


def _send(tx, step):
    data = _hx(step["data"])
    if step["op"] == "seal":
        return tx.seal(data)
    if step["op"] == "control":
        return tx.control(InnerType[step["inner"]], data)
    return [tx.close_frame(1000, data.decode())]


@pytest.mark.parametrize("ib,rb", PAIRS)
@pytest.mark.parametrize("name", sorted(TRANSCRIPTS))
def test_transcript_bytes(name, ib, rb):
    """Рукопожатие и транспорт байт в байт при любой паре движков."""
    t = TRANSCRIPTS[name]
    sides = _handshakes(t, ib, rb)
    _run_handshake(t, sides)
    ch = _channels(t, sides)
    for n, step in enumerate(t["transport"]):
        frames = _send(ch[step["from"]], step)
        assert [f.hex() for f in frames] == step["frames"], (name, n)
        events = [[k.name, d.hex()] for f in frames for k, d in ch[OTHER[step["from"]]].open(f)]
        assert events == step["events"], (name, n)
    assert {w: [c.rekeys_sent, c.rekeys_received] for w, c in ch.items()} == t["rekeys"]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("name", sorted(TRANSCRIPTS))
def test_transcript_receive_only(name, backend):
    """Получатель принимает записанные кадры (без собственной отправки)."""
    t = TRANSCRIPTS[name]
    sides = _handshakes(t, backend, backend)
    _run_handshake(t, sides)
    ch = _channels(t, sides)
    for step in t["transport"]:
        rx = ch[OTHER[step["from"]]]
        events = [[k.name, d.hex()] for f in step["frames"] for k, d in rx.open(_hx(f))]
        assert events == step["events"]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("name", sorted(TRANSCRIPTS))
def test_transcript_rekey_frame_cannot_be_skipped(name, backend):
    """Выброшенный кадр REKEY (или любой другой) — IntegrityError на следующем."""
    t = TRANSCRIPTS[name]
    sides = _handshakes(t, backend, backend)
    _run_handshake(t, sides)
    ch = _channels(t, sides)
    for step in t["transport"]:
        rx = ch[OTHER[step["from"]]]
        frames = [_hx(f) for f in step["frames"]]
        if len(frames) > 1:                 # [REKEY, ...]
            with pytest.raises(IntegrityError):
                rx.open(frames[1])
            return
        rx.open(frames[0])
    pytest.fail("в транскрипте нет rekey")


def test_vectors_follow_protocol():
    """Прологи §3.1, порядок кадров §3.2–3.3, PSK §3.4, PAIRED §4.1."""
    ik, xx = TRANSCRIPTS["ik_session"], TRANSCRIPTS["xxpsk3_pairing"]
    assert _hx(ik["prologue"]) == PROLOGUE_SESSION == b"sakura-securechannel/1\x00session"
    assert _hx(xx["prologue"]) == PROLOGUE_PAIR == b"sakura-securechannel/1\x00pair"
    assert ik["protocol_name"] == "Noise_IK_25519_ChaChaPoly_BLAKE2s"
    assert xx["protocol_name"] == "Noise_XXpsk3_25519_ChaChaPoly_BLAKE2s"
    assert [m["frame_type"] for m in ik["handshake"]] == ["IK_INIT", "IK_RESP"]
    assert [m["frame_type"] for m in xx["handshake"]] == ["XX_1", "XX_2", "XX_3"]
    assert set(json.loads(ik["handshake"][0]["payload_text"])) == {"v", "device_id", "ts"}
    assert xx["handshake"][0]["payload"] == xx["handshake"][1]["payload"] == ""
    assert _hx(xx["psk"]) == words_to_psk(xx["pair_words"])
    for t in (ik, xx):
        for side in ("initiator", "responder"):
            assert public_key(_hx(t[f"{side}_static"])).hex() == t[f"{side}_static_pub"]
        assert all(n >= 1 for pair in t["rekeys"].values() for n in pair)
    paired = xx["transport"][0]
    assert paired["inner"] == "PAIRED"
    assert json.loads(paired["text"])["server_pub"] == b64url(_hx(xx["responder_static_pub"]))


def test_vectors_file_is_current():
    """Файл совпадает с генератором (детерминированность, никто не правил руками)."""
    spec = importlib.util.spec_from_file_location("gen_interop_vectors",
                                                  ROOT / "scripts" / "gen_interop_vectors.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    path = ROOT / "securechannel" / "vectors" / "interop.json"
    assert gen.render(gen.build("lib")) == path.read_text("utf-8")
    assert gen.render(gen.build("edu")) == path.read_text("utf-8")
