"""securechannel: кадры, фрагментация, канал (rekey, повтор, перестановка,
подмена), свойства (hypothesis) и простой фаззер парсера.

Run: python -m pytest tests/test_securechannel_frames.py -q
"""

import random
import struct

import pytest

from securechannel.channel import SecureChannel, parse_close
from securechannel.frames import (
    FLAG_MORE,
    HEADER_LEN,
    MAX_BODY,
    MAX_CHUNK,
    MAX_FRAGMENTS,
    MAX_MESSAGE,
    FrameError,
    FrameType,
    InnerType,
    Reassembler,
    TooLarge,
    decode_frame,
    decode_inner,
    encode_frame,
    encode_inner,
    fragment,
    is_secure_frame,
)
from securechannel.handshake import Handshake, IntegrityError, generate_keypair

hyp = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402


# ── формат кадра ──────────────────────────────────────────────────

def test_frame_layout_is_fixed():
    f = encode_frame(FrameType.IK_INIT, b"abc")
    assert f == b"SK\x01\x01\x00\x00\x00\x03abc"
    assert HEADER_LEN == 8 and MAX_CHUNK == 65517
    assert decode_frame(f) == (FrameType.IK_INIT, b"abc")
    assert is_secure_frame(f) and not is_secure_frame('{"type":"register"}')


@pytest.mark.parametrize("raw,why", [
    (b"", "короче"), (b"SK\x01", "короче"), (b"XX\x01\x01\x00\x00\x00\x00", "магия"),
    (b"SK\x02\x01\x00\x00\x00\x00", "версия"), (b"SK\x01\x99\x00\x00\x00\x00", "тип"),
    (b"SK\x01\x01\x00\x00\x00\x05abc", "длина"), (b"SK\x01\x01\x00\x00\x00\x01abc", "длина"),
    (b"SK\x01\x01\x00\x01\x00\x00", "максимум"), ("SK", "бинарн"),
])
def test_decode_frame_rejects(raw, why):
    with pytest.raises(FrameError):
        decode_frame(raw)


def test_encode_limits():
    with pytest.raises(FrameError):
        encode_frame(FrameType.TRANSPORT, b"x" * (MAX_BODY + 1))
    with pytest.raises(FrameError):
        encode_inner(InnerType.DATA, 0x02)
    with pytest.raises(FrameError):
        encode_inner(InnerType.PING, FLAG_MORE)
    with pytest.raises(FrameError):
        encode_inner(InnerType.DATA, 0, b"x" * (MAX_CHUNK + 1))
    for bad in (b"", b"\x01", b"\x77\x00", b"\x01\x02", b"\x04\x01"):
        with pytest.raises(FrameError):
            decode_inner(bad)


@settings(max_examples=200, deadline=None)
@given(st.sampled_from(list(FrameType)), st.binary(max_size=2000))
def test_frame_roundtrip(ftype, body):
    assert decode_frame(encode_frame(ftype, body)) == (ftype, body)


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=3 * MAX_CHUNK + 7))
def test_fragment_reassemble_roundtrip(n):
    msg = random.Random(n).randbytes(n)
    parts = fragment(msg)
    assert all(len(c) <= MAX_CHUNK for _, c in parts)
    assert [f for f, _ in parts[:-1]] == [FLAG_MORE] * (len(parts) - 1) and parts[-1][0] == 0
    r = Reassembler()
    out = [r.feed(f, c) for f, c in parts]
    assert out[:-1] == [None] * (len(parts) - 1) and out[-1] == msg


def test_fragment_limits():
    assert len(fragment(b"x" * MAX_MESSAGE)) <= MAX_FRAGMENTS
    with pytest.raises(TooLarge):
        fragment(b"x" * (MAX_MESSAGE + 1))
    r = Reassembler()
    with pytest.raises(TooLarge):
        for _ in range(MAX_FRAGMENTS + 1):
            r.feed(FLAG_MORE, b"")            # переполнение числа кусков
    r = Reassembler(max_message=10)
    with pytest.raises(TooLarge):
        r.feed(FLAG_MORE, b"x" * 11)


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=64))
def test_parser_fuzz_only_frame_errors(data):
    """Произвольные байты: либо корректный кадр, либо FrameError — без
    других исключений."""
    try:
        ftype, body = decode_frame(data)
        assert encode_frame(ftype, body) == data
    except FrameError:
        pass
    try:
        decode_inner(data)
    except FrameError:
        pass


def test_mutation_fuzz_on_valid_frames():
    rng = random.Random(7)
    base = encode_frame(FrameType.TRANSPORT, rng.randbytes(40))
    for _ in range(3000):
        m = bytearray(base)
        for _ in range(rng.randint(1, 4)):
            op = rng.random()
            if op < 0.5 and m:
                m[rng.randrange(len(m))] ^= 1 << rng.randrange(8)
            elif op < 0.75 and m:
                del m[rng.randrange(len(m))]
            else:
                m.insert(rng.randrange(len(m) + 1), rng.randrange(256))
        try:
            decode_frame(bytes(m))
        except FrameError:
            pass


# ── канал ─────────────────────────────────────────────────────────

def _pair(backend="lib", **kw):
    (ip, _), (rp, rpub) = generate_keypair(), generate_keypair()
    i, r = Handshake.ik_initiator(ip, rpub, backend=backend), Handshake.ik_responder(rp, backend=backend)
    r.read(i.write())
    i.read(r.write())
    (si, ri), (sr, rr) = i.split(), r.split()
    return SecureChannel(si, ri, **kw), SecureChannel(sr, rr, **kw)


@pytest.mark.parametrize("backend", ["lib", "edu"])
def test_channel_roundtrip_fragmented(backend):
    a, b = _pair(backend)
    msg = random.Random(1).randbytes(MAX_CHUNK * 2 + 5)
    frames = a.seal(msg)
    assert len(frames) == 3
    events = [e for f in frames for e in b.open(f)]
    assert events == [(InnerType.DATA, msg)]
    assert b.open(a.seal(b"")[0]) == [(InnerType.DATA, b"")]


def test_channel_rekey_by_count_and_time():
    t = [0.0]
    a, b = _pair(rekey_messages=3, rekey_seconds=100, clock=lambda: t[0])
    out = []
    for k in range(7):
        for f in a.seal(b"m%d" % k):
            out += b.open(f)
    assert [d for _, d in out] == [b"m%d" % k for k in range(7)]
    assert a.rekeys_sent == 2 and b.rekeys_received == 2
    t[0] = 101.0
    for f in a.seal(b"after time"):
        assert b.open(f) in ([], [(InnerType.DATA, b"after time")])
    assert a.rekeys_sent == 3 and b.rekeys_received == 3


def test_channel_control_close_ping():
    a, b = _pair()
    (f,) = a.control(InnerType.PING, b"p")
    assert b.open(f) == [(InnerType.PING, b"p")]
    ev = b.open(a.close_frame(4409, "integrity"))
    assert ev[0][0] == InnerType.CLOSE and parse_close(ev[0][1]) == (4409, "integrity")
    with pytest.raises(FrameError):
        parse_close(b"\x01")


def test_channel_rejects_replay_reorder_tamper_truncation():
    a, b = _pair()
    f1, f2, f3 = (a.seal(b"%d" % k)[0] for k in range(3))
    assert b.open(f1) == [(InnerType.DATA, b"0")]
    with pytest.raises(IntegrityError):
        b.open(f1)                                 # повтор
    with pytest.raises(IntegrityError):
        b.open(f3)                                 # перестановка
    t = bytearray(f2)
    t[-1] ^= 0x80
    with pytest.raises(IntegrityError):
        b.open(bytes(t))                           # бит-флип в теге
    with pytest.raises(FrameError):
        b.open(f2[:-3])                            # обрезка: длина не совпадает
    cut = encode_frame(FrameType.TRANSPORT, decode_frame(f2)[1][:-3])
    with pytest.raises(IntegrityError):
        b.open(cut)                                # обрезка с поправленной длиной
    assert b.open(f2) == [(InnerType.DATA, b"1")]
    with pytest.raises(FrameError):
        b.open(encode_frame(FrameType.IK_INIT, b"x"))   # не TRANSPORT после рукопожатия


def test_channel_control_in_middle_of_message_rejected():
    a, b = _pair()
    # злонамеренный отправитель: кусок с MORE, затем CLOSE (счётчики верные)
    assert b.open(a._frame(InnerType.DATA, FLAG_MORE, b"part")) == []
    with pytest.raises(FrameError):
        b.open(a.close_frame(1000))


def test_channel_header_tamper_is_detected():
    """Внутренний заголовок (тип, MORE) под AEAD: внешний кадр не меняет смысл."""
    a, b = _pair()
    f = bytearray(a.seal(b"hello")[0])
    struct.pack_into(">I", f, 4, len(f) - HEADER_LEN)     # длина та же
    f[3] = FrameType.IK_RESP                                 # подменили внешний тип
    with pytest.raises(FrameError):
        b.open(bytes(f))
