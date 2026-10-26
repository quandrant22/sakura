"""Детерминированные транскрипты securechannel/1 для JUnit-тестов Android-клиента.

Эталон — серверный пакет securechannel/ (движок backend="lib", noiseprotocol, как на проде).
Ключи и эфемерные ключи фиксированы, поэтому кадры воспроизводимы побайтно. Клиент на Java
обязан выдать те же байты (SecureChannelTranscriptTest).

    py -3.11 -m venv mobile/android/tools/.venv
    mobile/android/tools/.venv/Scripts/pip install cryptography noiseprotocol
    mobile/android/tools/.venv/Scripts/python mobile/android/tools/gen_sc_transcripts.py

Пишет app/src/test/resources/sc_transcripts.json. Сервер не меняется: пакет только импортируется.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]          # корень репозитория
sys.path.insert(0, str(ROOT))

from securechannel.channel import SecureChannel  # noqa: E402
from securechannel.frames import FrameType, InnerType, encode_frame  # noqa: E402
from securechannel.handshake import Handshake, public_key  # noqa: E402
from securechannel.keys import b64url, fingerprint  # noqa: E402
from securechannel.pairing import words_to_psk  # noqa: E402

OUT = HERE.parent / "app" / "src" / "test" / "resources" / "sc_transcripts.json"


def key(label: str) -> bytes:
    """Детерминированный 32-байтный ключ из метки."""
    return hashlib.blake2s(b"sakura-test-key/" + label.encode()).digest()


def fixed_clock() -> float:
    return 1000.0


def messages_c2s_s2c(client: SecureChannel, server: SecureChannel, big: bytes) -> list[dict]:
    """3 сообщения туда-обратно и одно большое (фрагментированное) от клиента."""
    plan = [
        ("c2s", b'{"type":"register","device_id":"phone","proto":2}'),
        ("s2c", '{"type":"registered","text":"Привет"}'.encode("utf-8")),
        ("c2s", b'{"type":"ping"}'),
        ("c2s", big),
    ]
    out = []
    for direction, msg in plan:
        sender, receiver = (client, server) if direction == "c2s" else (server, client)
        frames = sender.seal(msg)
        got = []
        for f in frames:
            got += receiver.open(f)
        assert got == [(InnerType.DATA, msg)], direction
        out.append({"dir": direction, "message_hex": msg.hex(), "frames_hex": [f.hex() for f in frames]})
    return out


def ik(rekey_messages: int) -> dict:
    c_s, s_s, c_e, s_e = key("ik-client-static"), key("ik-server-static"), key("ik-client-eph"), key("ik-server-eph")
    s_pub = public_key(s_s)
    init = Handshake.ik_initiator(c_s, s_pub, e_priv=c_e)
    resp = Handshake.ik_responder(s_s, e_priv=s_e)
    p1 = json.dumps({"v": 1, "device_id": "phone", "ts": 1791900000.5}, separators=(",", ":")).encode()
    m1 = init.write(p1)
    assert resp.read(m1) == p1
    p2 = json.dumps({"v": 1, "session": "0123456789abcdef", "rekey_messages": rekey_messages,
                     "rekey_seconds": 3600, "server_time": 1791900000.0}, separators=(",", ":")).encode()
    m2 = resp.write(p2)
    assert init.read(m2) == p2
    assert init.handshake_hash == resp.handshake_hash
    cs, cr = init.split()
    ss, sr = resp.split()
    client = SecureChannel(cs, cr, rekey_messages=rekey_messages, clock=fixed_clock)
    server = SecureChannel(ss, sr, rekey_messages=rekey_messages, clock=fixed_clock)
    big = bytes((i * 7 + 3) % 251 for i in range(70_000))
    return {
        "pattern": "IK",
        "rekey_messages": rekey_messages,
        "client_static": c_s.hex(), "server_static": s_s.hex(),
        "client_ephemeral": c_e.hex(), "server_ephemeral": s_e.hex(),
        "server_pub": s_pub.hex(), "server_pub_b64url": b64url(s_pub), "server_fp": fingerprint(s_pub),
        "payload1_hex": p1.hex(), "payload2_hex": p2.hex(),
        "frame1_hex": encode_frame(FrameType.IK_INIT, m1).hex(),
        "frame2_hex": encode_frame(FrameType.IK_RESP, m2).hex(),
        "handshake_hash": init.handshake_hash.hex(),
        "transport": messages_c2s_s2c(client, server, big),
    }


def xx() -> dict:
    words = "лес кот мост река гора снег дом сад"
    psk = words_to_psk(words)
    c_s, s_s, c_e, s_e = key("xx-client-static"), key("xx-server-static"), key("xx-client-eph"), key("xx-server-eph")
    init = Handshake.xx_initiator(c_s, psk, e_priv=c_e)
    resp = Handshake.xx_responder(s_s, psk, e_priv=s_e)
    m1 = init.write(b"")
    resp.read(m1)
    m2 = resp.write(b"")
    init.read(m2)
    p3 = json.dumps({"v": 1, "name": "Телефон", "kind": "phone", "device_id_hint": "phone"},
                    ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    m3 = init.write(p3)
    assert resp.read(m3) == p3
    assert resp.remote_static == public_key(c_s)
    cs, cr = init.split()
    ss, sr = resp.split()
    client = SecureChannel(cs, cr, clock=fixed_clock)
    server = SecureChannel(ss, sr, clock=fixed_clock)
    s_pub = public_key(s_s)
    paired = json.dumps({"device_id": "phone", "server_pub": b64url(s_pub), "server_fp": fingerprint(s_pub)},
                        separators=(",", ":")).encode()
    paired_frames = server.control(InnerType.PAIRED, paired)
    got = []
    for f in paired_frames:
        got += client.open(f)
    assert got == [(InnerType.PAIRED, paired)]
    big = bytes((i * 13 + 5) % 253 for i in range(66_000))
    return {
        "pattern": "XXpsk3",
        "words": words, "psk": psk.hex(),
        "client_static": c_s.hex(), "server_static": s_s.hex(),
        "client_ephemeral": c_e.hex(), "server_ephemeral": s_e.hex(),
        "server_pub": s_pub.hex(), "server_fp": fingerprint(s_pub),
        "payload3_hex": p3.hex(),
        "frame1_hex": encode_frame(FrameType.XX_1, m1).hex(),
        "frame2_hex": encode_frame(FrameType.XX_2, m2).hex(),
        "frame3_hex": encode_frame(FrameType.XX_3, m3).hex(),
        "handshake_hash": init.handshake_hash.hex(),
        "paired_hex": paired.hex(),
        "paired_frames_hex": [f.hex() for f in paired_frames],
        "transport": messages_c2s_s2c(client, server, big),
    }


def main() -> None:
    data = {
        "generator": "mobile/android/tools/gen_sc_transcripts.py",
        "engine": "securechannel backend=lib (noiseprotocol)",
        "transcripts": [ik(10000), ik(2), xx()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"записано {OUT.relative_to(ROOT)}: {len(data['transcripts'])} транскрипта")


if __name__ == "__main__":
    main()
