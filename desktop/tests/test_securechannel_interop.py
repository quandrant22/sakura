"""Совместимость клиентского Noise с noiseprotocol (MIT; им пользуется сервер): IK и XXpsk3 в обе стороны.

Пропускается, если noiseprotocol не установлен (в venv агента его нет — проверка в отдельном venv:
python -m pytest desktop/tests/test_securechannel_interop.py с noiseprotocol и cryptography).
"""
import os

import pytest

noise_lib = pytest.importorskip("noise.connection")
from cryptography.exceptions import InvalidTag  # noqa: E402
from noise.connection import Keypair, NoiseConnection  # noqa: E402

from desktop.core.securechannel import noise as N  # noqa: E402

PRO_IK = b"sakura-securechannel/1\x00session"
PRO_XX = b"sakura-securechannel/1\x00pair"


def lib(name, responder, prologue, s_priv, rs=None, psk=None):
    c = NoiseConnection.from_name(name)
    c.set_as_responder() if responder else c.set_as_initiator()
    c.set_keypair_from_private_bytes(Keypair.STATIC, s_priv)
    if rs is not None:
        c.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, rs)
    if psk is not None:
        c.set_psks(psk=psk)
    c.set_prologue(prologue)
    c.start_handshake()
    return c


def keys():
    return N.generate_keypair(), N.generate_keypair()


def transport_roundtrip(my_send, my_recv, peer):
    for i in range(3):
        msg = f"сообщение {i}".encode()
        assert peer.decrypt(my_send.encrypt_with_ad(b"", msg)) == msg
        assert my_recv.decrypt_with_ad(b"", peer.encrypt(msg + b"!")) == msg + b"!"
    # rekey в обе стороны
    my_send.rekey()
    peer.noise_protocol.cipher_state_decrypt.rekey()
    assert peer.decrypt(my_send.encrypt_with_ad(b"", b"after rekey")) == b"after rekey"


def test_ik_client_initiator_vs_lib_responder():
    (c_priv, c_pub), (s_priv, s_pub) = keys()
    me = N.HandshakeState("IK", True, PRO_IK, s_priv=c_priv, rs=s_pub)
    srv = lib(b"Noise_IK_25519_ChaChaPoly_BLAKE2s", True, PRO_IK, s_priv)
    assert srv.read_message(me.write(b'{"v":1,"device_id":"pc"}')) == b'{"v":1,"device_id":"pc"}'
    assert me.read(srv.write_message(b'{"v":1,"session":"ab"}')) == b'{"v":1,"session":"ab"}'
    assert me.complete and srv.handshake_finished and me.handshake_hash == srv.get_handshake_hash()
    send, recv = me.split()
    transport_roundtrip(send, recv, srv)


def test_ik_lib_initiator_vs_client_responder():
    (c_priv, c_pub), (s_priv, s_pub) = keys()
    cli = lib(b"Noise_IK_25519_ChaChaPoly_BLAKE2s", False, PRO_IK, c_priv, rs=s_pub)
    me = N.HandshakeState("IK", False, PRO_IK, s_priv=s_priv)
    assert me.read(cli.write_message(b"hi")) == b"hi" and me.remote_static == c_pub
    assert cli.read_message(me.write(b"ok")) == b"ok"
    assert me.handshake_hash == cli.get_handshake_hash()


def test_xxpsk3_client_initiator_vs_lib_responder():
    (c_priv, c_pub), (s_priv, s_pub) = keys()
    psk = os.urandom(32)
    me = N.HandshakeState("XXpsk3", True, PRO_XX, s_priv=c_priv, psk=psk)
    srv = lib(b"Noise_XXpsk3_25519_ChaChaPoly_BLAKE2s", True, PRO_XX, s_priv, psk=psk)
    srv.read_message(me.write(b""))
    me.read(srv.write_message(b""))
    assert me.remote_static == s_pub
    srv.read_message(me.write(b'{"v":1,"name":"PC"}'))
    assert me.complete and srv.handshake_finished and me.handshake_hash == srv.get_handshake_hash()
    send, recv = me.split()
    transport_roundtrip(send, recv, srv)


def test_xxpsk3_wrong_psk_fails():
    (c_priv, _), (s_priv, _) = keys()
    me = N.HandshakeState("XXpsk3", True, PRO_XX, s_priv=c_priv, psk=os.urandom(32))
    srv = lib(b"Noise_XXpsk3_25519_ChaChaPoly_BLAKE2s", True, PRO_XX, s_priv, psk=os.urandom(32))
    srv.read_message(me.write(b""))
    me.read(srv.write_message(b""))
    with pytest.raises(InvalidTag):
        srv.read_message(me.write(b"x"))


def test_prologue_binds_purpose():
    """Сообщение XX нельзя выдать за IK: другой пролог — хеши расходятся, рукопожатие падает."""
    (c_priv, _), (s_priv, s_pub) = keys()
    me = N.HandshakeState("IK", True, PRO_XX, s_priv=c_priv, rs=s_pub)
    srv = lib(b"Noise_IK_25519_ChaChaPoly_BLAKE2s", True, PRO_IK, s_priv)
    with pytest.raises(InvalidTag):
        srv.read_message(me.write(b"x"))
