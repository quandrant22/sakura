"""Соединения через публичный nginx (wss:// на :443) не считаются локальными.

За обратным прокси remote_address всегда 127.0.0.1; без метки X-Sakura-Edge
вход по токену получил бы secure=true без Noise (регрессия выката wss, 2026-11-10).
"""
from types import SimpleNamespace

from sakura_core import secure_policy


def _ws(remote, headers=None):
    req = SimpleNamespace(headers=headers or {}) if headers is not None else None
    return SimpleNamespace(remote_address=remote, request=req)


def test_direct_loopback_is_local():
    ws = _ws(("127.0.0.1", 40000), headers={})
    assert secure_policy.peer_ip(ws) == "127.0.0.1"
    assert secure_policy.is_local_peer(secure_policy.peer_ip(ws))


def test_edge_marked_loopback_is_not_local():
    ws = _ws(("127.0.0.1", 40001), headers={"X-Sakura-Edge": "1"})
    assert secure_policy.via_edge(ws)
    assert secure_policy.peer_ip(ws) is None
    assert not secure_policy.is_local_peer(secure_policy.peer_ip(ws))


def test_no_request_object_falls_back_to_socket():
    ws = SimpleNamespace(remote_address=("::1", 1))
    assert not secure_policy.via_edge(ws)
    assert secure_policy.is_local_peer(secure_policy.peer_ip(ws))
