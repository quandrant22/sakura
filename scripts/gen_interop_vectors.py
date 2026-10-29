#!/usr/bin/env python3
"""Интероп-векторы securechannel/1: детерминированные транскрипты IK и XXpsk3.

  python scripts/gen_interop_vectors.py           # записать securechannel/vectors/interop.json
  python scripts/gen_interop_vectors.py --check   # только сверить файл с генератором

Все ключи (статические и эфемерные) выводятся из меток через BLAKE2s — запуск
воспроизводим байт в байт. Транскрипт = кадры рукопожатия (PROTOCOL.md §3,
прологи §3.1) + транспорт SecureChannel (§4) с rekey каждые rekey_messages
кадров. Рукопожатие пишется учебным движком (backend="edu") и сверяется с
библиотекой (backend="lib") до записи; tests/test_securechannel_interop.py
прогоняет файл через оба движка. Пишет только файл векторов.
"""

import argparse
import hashlib
import json
import os
import sys
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "securechannel", "vectors", "interop.json")
KEY_CONTEXT = b"sakura-interop/1\x00"
PAIR_WORDS = "лес кот мост река гора снег луна поле"


def fixed_priv(label: str) -> bytes:
    """Детерминированный закрытый ключ X25519 из метки (зажим делает X25519)."""
    return hashlib.blake2s(KEY_CONTEXT + label.encode(), digest_size=32).digest()


def _json(obj) -> bytes:
    return json.dumps(obj).encode()          # как в server.py / client.py


def _setup():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    # noiseprotocol предупреждает о заданных эфемерных ключах — для векторов это и нужно.
    warnings.filterwarnings("ignore", message="One of ephemeral keypairs")


# Транспорт после рукопожатия: (кто, операция, внутренний тип, данные).
# seal — сообщение приложения (DATA), control — служебный кадр, close — CLOSE.
IK_TRANSPORT = [
    ("initiator", "seal", "DATA", _json({"type": "register", "device_id": "mostech"})),
    ("responder", "seal", "DATA", _json({"type": "registered", "device_id": "mostech"})),
    ("initiator", "control", "PING", b"ping-1"),
    ("initiator", "seal", "DATA", _json({"type": "voice_command", "text": "привет"})),
    ("responder", "seal", "DATA", _json({"type": "reply", "text": "привет, мастер"})),
    ("responder", "control", "PONG", b"ping-1"),
    ("initiator", "seal", "DATA", _json({"type": "ping"})),
    ("initiator", "close", "CLOSE", b"bye"),
]
XX_TRANSPORT = [
    ("responder", "control", "PAIRED", None),        # данные — из ключа сервера
    ("initiator", "seal", "DATA", _json({"type": "ack"})),
    ("responder", "seal", "DATA", _json({"type": "note", "text": "rekey"})),
    ("initiator", "seal", "DATA", _json({"type": "ack", "n": 2})),
    ("responder", "close", "CLOSE", b"paired"),
]


def _transcript(name: str, pattern: str, backend: str) -> dict:
    from securechannel.channel import SecureChannel
    from securechannel.frames import FrameType, InnerType, encode_frame
    from securechannel.handshake import (
        PROLOGUE_PAIR,
        PROLOGUE_SESSION,
        Handshake,
        public_key,
    )
    from securechannel.keys import b64url, fingerprint
    from securechannel.noise.core import protocol_name
    from securechannel.pairing import normalize_words, words_to_psk

    ik = pattern == "IK"
    tag = "ik" if ik else "xx"
    keys = {
        "initiator_static": fixed_priv("client-static"),
        "responder_static": fixed_priv("server-static"),
        "initiator_ephemeral": fixed_priv(f"{tag}-client-ephemeral"),
        "responder_ephemeral": fixed_priv(f"{tag}-server-ephemeral"),
    }
    i_pub, r_pub = public_key(keys["initiator_static"]), public_key(keys["responder_static"])
    psk = None if ik else words_to_psk(PAIR_WORDS)
    if ik:
        i = Handshake.ik_initiator(keys["initiator_static"], r_pub, backend=backend,
                                   e_priv=keys["initiator_ephemeral"])
        r = Handshake.ik_responder(keys["responder_static"], backend=backend,
                                   e_priv=keys["responder_ephemeral"])
        steps = [("initiator", FrameType.IK_INIT,
                  _json({"v": 1, "device_id": "mostech", "ts": 1791900000.0})),
                 ("responder", FrameType.IK_RESP,
                  _json({"v": 1, "session": "0123456789abcdef", "rekey_messages": 2,
                         "rekey_seconds": 3600.0, "server_time": 1791900000.5}))]
        transport, rekey_messages = IK_TRANSPORT, 2
    else:
        i = Handshake.xx_initiator(keys["initiator_static"], psk, backend=backend,
                                   e_priv=keys["initiator_ephemeral"])
        r = Handshake.xx_responder(keys["responder_static"], psk, backend=backend,
                                   e_priv=keys["responder_ephemeral"])
        steps = [("initiator", FrameType.XX_1, b""),
                 ("responder", FrameType.XX_2, b""),
                 ("initiator", FrameType.XX_3,
                  _json({"v": 1, "name": "Ноутбук", "kind": "pc",
                         "device_id_hint": "mostech"}))]
        transport, rekey_messages = XX_TRANSPORT, 1
    sides = {"initiator": i, "responder": r}

    handshake = []
    for who, ftype, payload in steps:
        writer = sides[who]
        reader = sides["responder" if who == "initiator" else "initiator"]
        msg = writer.write(payload)
        if reader.read(msg) != payload:
            raise RuntimeError(f"{name}: payload {ftype.name} не совпал")
        handshake.append({"from": who, "frame_type": ftype.name, "payload": payload.hex(),
                          "payload_text": payload.decode(), "message": msg.hex(),
                          "frame": encode_frame(ftype, msg).hex()})
    if i.handshake_hash != r.handshake_hash:
        raise RuntimeError(f"{name}: хеши рукопожатия разошлись")
    if i.remote_static != r_pub or r.remote_static != i_pub:
        raise RuntimeError(f"{name}: статические ключи не переданы")

    # Часы стоят: rekey только по счётчику кадров — транскрипт не зависит от времени.
    channels = {who: SecureChannel(*hs.split(), rekey_messages=rekey_messages,
                                   clock=lambda: 0.0)
                for who, hs in sides.items()}
    paired = _json({"device_id": "mostech", "server_pub": b64url(r_pub),
                    "server_fp": fingerprint(r_pub)})
    steps_out = []
    for who, op, inner, data in transport:
        data = paired if data is None else data
        tx = channels[who]
        rx = channels["responder" if who == "initiator" else "initiator"]
        if op == "seal":
            frames = tx.seal(data)
        elif op == "control":
            frames = tx.control(InnerType[inner], data)
        else:
            frames = [tx.close_frame(1000, data.decode())]
        events = [[t.name, d.hex()] for f in frames for t, d in rx.open(f)]
        steps_out.append({"from": who, "op": op, "inner": inner, "data": data.hex(),
                          "text": data.decode(), "frames": [f.hex() for f in frames],
                          "events": events})
    return {
        "name": name,
        "protocol_name": protocol_name(pattern).decode(),
        "pattern": pattern,
        "prologue": (PROLOGUE_SESSION if ik else PROLOGUE_PAIR).hex(),
        "initiator_static": keys["initiator_static"].hex(),
        "initiator_static_pub": i_pub.hex(),
        "initiator_ephemeral": keys["initiator_ephemeral"].hex(),
        "responder_static": keys["responder_static"].hex(),
        "responder_static_pub": r_pub.hex(),
        "responder_ephemeral": keys["responder_ephemeral"].hex(),
        "pair_words": None if ik else normalize_words(PAIR_WORDS),
        "psk": None if ik else psk.hex(),
        "handshake": handshake,
        "handshake_hash": i.handshake_hash.hex(),
        "rekey_messages": rekey_messages,
        "transport": steps_out,
        "rekeys": {who: [ch.rekeys_sent, ch.rekeys_received] for who, ch in channels.items()},
    }


def build(backend: str = "edu") -> dict:
    """Весь файл векторов; backend — движок рукопожатия и транспорта."""
    _setup()
    return {
        "description": "securechannel/1: детерминированные транскрипты IK (сеанс) и XXpsk3 "
                       "(спаривание) с транспортом и rekey. Ключи — BLAKE2s(KEY_CONTEXT ‖ метка).",
        "generator": "scripts/gen_interop_vectors.py",
        "key_context": KEY_CONTEXT.hex(),
        "transcripts": [_transcript("ik_session", "IK", backend),
                        _transcript("xxpsk3_pairing", "XXpsk3", backend)],
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="не писать, только сверить файл")
    args = ap.parse_args(argv)
    text = render(build("edu"))
    if text != render(build("lib")):
        print("edu и lib дали разные транскрипты — файл не записан", file=sys.stderr)
        return 1
    if args.check:
        try:
            with open(OUT, encoding="utf-8") as f:
                same = f.read() == text
        except FileNotFoundError:
            same = False
        print("актуален" if same else f"устарел: {OUT}")
        return 0 if same else 1
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"записан {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
