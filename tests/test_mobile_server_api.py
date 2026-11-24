"""Тесты серверной интеграции мобильного пульта, silent-режима и голосового STT."""
import asyncio
import base64
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.state as st
from sakura_core import proto_devices, proto_mobile, proto_v2, voice_turns


class _FakeWS:
    def __init__(self, secure=True):
        self.sent = []
        self._secure = secure

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.fixture(autouse=True)
def _clean_devices():
    prev = dict(st.connected_devices)
    prev_proto = dict(st.device_proto)
    prev_tracks = dict(st.device_tracks)
    yield
    st.connected_devices.clear()
    st.connected_devices.update(prev)
    st.device_proto.clear()
    st.device_proto.update(prev_proto)
    st.device_tracks.clear()
    st.device_tracks.update(prev_tracks)


def test_silent_turn_skips_tts_and_sends_reply():
    import modules.tts_server as tts

    ws = _FakeWS()
    called_synth = []

    async def fake_synth(*a, **kw):
        called_synth.append(a)
        return 1

    async def run():
        token = voice_turns._current.set(
            voice_turns.Turn(turn_id="t1", device_id="phone", ws=ws, speak=False)
        )
        try:
            assert voice_turns.is_silent() is True
            assert await tts.preconnect() is False
            with patch.object(tts, "_synthesize_and_stream", fake_synth), \
                 patch.object(tts, "send_spoken_reply", AsyncMock()) as mock_reply:
                await tts.stream_tts_to_device(
                    "Привет, Мастер!", ws, "phone", reply_kind="llm"
                )
            assert called_synth == []
            mock_reply.assert_awaited_once_with("Привет, Мастер!", ws, "phone", "llm")
            await tts.ensure_turn_end(ws, "phone", 0.0)
            assert ws.sent == []
        finally:
            voice_turns._current.reset(token)

    asyncio.run(run())


def test_remote_command_requires_online_pc_and_sends_confirmed():
    pc_ws = _FakeWS()
    st.connected_devices["pc"] = pc_ws
    st.device_proto["pc"] = 2

    res = asyncio.run(proto_mobile._remote_command(
        _FakeWS(),
        {"type": "remote_command", "device_id": "phone", "action": "system.volume_up", "arg": "15"},
        {},
    ))
    assert res["type"] == "remote_command_ok"
    assert res["target"] == "pc"
    assert pc_ws.sent[0]["type"] == "command"
    assert pc_ws.sent[0]["action"] == "system.volume"
    assert pc_ws.sent[0]["arg"] == "+15"
    assert pc_ws.sent[0]["confirmed"] is True


def test_remote_command_offline_raises_v2error():
    st.connected_devices.clear()
    with pytest.raises(proto_v2.V2Error) as exc:
        asyncio.run(proto_mobile._remote_command(
            _FakeWS(),
            {"type": "remote_command", "device_id": "phone", "target": "pc", "action": "system.shutdown"},
            {},
        ))
    assert exc.value.code == "offline"


def test_widgets_data_returns_schedule_memory_and_pc():
    st.connected_devices["pc"] = _FakeWS()
    lesson = SimpleNamespace(
        date=dt.date(2026, 11, 24),
        start=dt.time(10, 0),
        end=dt.time(11, 30),
        subject="Линейная алгебра",
        room="А-204",
        teacher="Иванов",
        kind_raw="Лекция",
    )
    with patch("sakura_core.schedule.query.has_data", return_value=True), \
         patch("sakura_core.schedule.query.is_stale", return_value=False), \
         patch("sakura_core.schedule.query.current_lesson", return_value=lesson), \
         patch("sakura_core.schedule.query.next_lesson", return_value=None), \
         patch("sakura_core.schedule.query.on", return_value=[lesson]), \
         patch("memory.db.list_memories", return_value=([], 7, {"факты": 7})):
        snap = proto_mobile._build_widgets_snapshot(dt.datetime(2026, 11, 24, 10, 30))

    assert snap["type"] == "widgets_data"
    assert snap["schedule"]["has_data"] is True
    assert snap["schedule"]["current"]["subject"] == "Линейная алгебра"
    assert len(snap["schedule"]["today"]) == 1
    assert snap["memory"]["total"] == 7
    assert snap["memory"]["counts"]["факты"] == 7
    assert snap["pc"]["id"] == "pc"
    assert snap["pc"]["online"] is True


def test_proto_devices_exposes_active_and_track():
    st.connected_devices["pc"] = _FakeWS()
    st.set_device_track("pc", {"title": "Neon Sakura", "artist": "Miku", "status": "playing"})
    d = proto_devices.device("pc", focus_id="pc")
    assert d["active"] is True
    assert d["track"]["title"] == "Neon Sakura"
    assert d["track"]["artist"] == "Miku"


def test_proto_devices_preserves_gpu_telemetry():
    stats = proto_devices._stats({
        "cpu": 25,
        "ram": 48,
        "gpu": 63,
        "gpu_temp": 61.0,
        "vram": 44.5,
        "gpu_name": "NVIDIA GeForce RTX 4060",
    })
    assert stats["gpu"] == 63
    assert stats["gpu_temp"] == 61.0
    assert stats["vram"] == 44.5
    assert stats["gpu_name"] == "NVIDIA GeForce RTX 4060"
    assert proto_devices._significant(
        {"stats": {"cpu": 25, "ram": 48, "gpu": 10}},
        {"stats": {"cpu": 25, "ram": 48, "gpu": 63}},
    ) is True


def test_voice_audio_transcribes_and_starts_silent_turn():
    import sakura_core.chat_hooks
    import sakura_core.llm

    phone_ws = _FakeWS()
    raw_audio = base64.b64encode(b"RIFF....WAVE").decode("ascii")
    started = []

    def fake_start(device_id, ws, factory, *, turn_id=None, speak=True):
        started.append((device_id, turn_id, speak))
        return voice_turns.Turn(turn_id=turn_id or "t", device_id=device_id, ws=ws, speak=speak)

    with patch("sakura_core.llm.transcribe_audio", AsyncMock(return_value="выключи свет")) as mock_stt, \
         patch("sakura_core.chat_hooks.record", AsyncMock(return_value=({"id": 42, "role": "user", "text": "выключи свет"}, True))), \
         patch("sakura_core.chat_hooks.push_message", AsyncMock()), \
         patch.object(voice_turns, "start", fake_start):
        res = asyncio.run(proto_mobile._voice_audio(
            phone_ws,
            {"type": "voice_audio", "device_id": "phone", "audio": raw_audio, "speak": False},
            {},
        ))

    mock_stt.assert_awaited_once()
    assert res["type"] == "voice_audio_ok"
    assert res["transcript"] == "выключи свет"
    assert started and started[0][0] == "phone" and started[0][2] is False


def test_proto_v2_lists_new_private_mobile_requests():
    for kind in ("remote_command", "widgets_data", "voice_audio"):
        assert proto_v2.is_v2(kind)
        assert proto_v2.is_private(kind)
