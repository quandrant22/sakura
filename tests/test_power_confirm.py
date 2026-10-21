"""Подтверждение выключения / перезагрузки / сна ПК (sakura_core/power_confirm).

Run: python -m pytest tests/test_power_confirm.py -q
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

import modules.state as st
import modules.tts_server as tts
from modules import presence_sync as ps
from sakura_core import bridge as br, power_confirm as pcm


class AgentWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def commands(self):
        return [m for m in self.sent if m.get("type") == "command"]


@pytest.fixture
def world(monkeypatch):
    """pc / laptop / mostech онлайн; озвучка и Telegram записываются."""
    ws = {d: AgentWS() for d in ("pc", "laptop", "mostech")}
    monkeypatch.setattr(st, "connected_devices", dict(ws))
    monkeypatch.setattr(st, "device_proto", {d: 2 for d in ws})      # proto 2: канонические имена
    ps.reset()
    monkeypatch.setattr(ps, "get_active_device", lambda: "pc")
    spoken, tg = [], []

    async def fake_tts(text, websocket, device_id, literal=False, emotion=None, stop=None,
                       listen=None, reply_kind="template"):
        spoken.append((device_id, text, reply_kind))
    monkeypatch.setattr(tts, "stream_tts_to_device", fake_tts)

    async def fake_tg(text, buttons=None):
        tg.append((text, buttons))
    monkeypatch.setattr(pcm, "_telegram", fake_tg)
    br.get_router().session.cancel()
    yield ws, spoken, tg
    br.get_router().session.cancel()
    ps.reset()


def say(text, device, ws, source=None):
    """Фраза Мастера через настоящий мост; возвращает то, что сказал speak."""
    out = []

    async def speak(phrase, listen=None):
        out.append(phrase)
    asyncio.run(br.v3_fast_path(
        text, data={"active_window": ""}, device_ws=ws[device] if device in ws else None,
        device_id=device, register_command=lambda a, d: "cmd1", speak=speak,
        source=source or device))
    return out


def answer(text, source):
    return asyncio.run(pcm.handle_answer(text, source))


def test_shutdown_asks_with_active_pc_name_then_yes_sends_confirmed(world):
    ws, spoken, _ = world
    assert say("выключи комп", "laptop", ws) == []          # мост молчит, вопрос задан сам
    assert spoken == [("laptop", "Выключить игровой компьютер? Да или нет?", "confirm")]
    assert all(w.commands() == [] for w in ws.values()), "без «да» ничего не уходит"
    assert answer("да", "laptop")
    (cmd,) = ws["pc"].commands()
    assert cmd["action"] == "system.shutdown" and cmd["confirmed"] is True
    assert ws["laptop"].commands() == [] and not st._pending_power


def test_no_cancels_and_sends_nothing(world):
    ws, spoken, _ = world
    say("перезагрузи ноутбук", "laptop", ws)
    assert spoken[0][1] == "Перезагрузить ноутбук? Да или нет?"
    assert answer("нет", "laptop")
    assert all(w.commands() == [] for w in ws.values()) and not st._pending_power
    assert not answer("да", "laptop"), "после «нет» «да» уже ничего не значит"


def test_yes_from_telegram_confirms_voice_question(world):
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)
    assert tg == [], "Мастер у ПК — вопрос в Telegram не дублируется"
    assert answer("да", "telegram")
    assert [c["action"] for c in ws["pc"].commands()] == ["system.shutdown"]
    assert tg and "Выключаю игровой компьютер" in tg[-1][0]     # ответ — туда, откуда «да»


def test_named_pc_wins_over_source_and_sleep_goes_to_it(world):
    ws, spoken, _ = world
    say("усыпи игровой", "laptop", ws)
    assert spoken[0][1] == "Усыпить игровой компьютер? Да или нет?"
    answer("да", "laptop")
    (cmd,) = ws["pc"].commands()
    assert cmd["action"] == "power.sleep" and cmd["confirmed"] is True
    assert ws["laptop"].commands() == []


def test_work_laptop_by_name(world):
    ws, spoken, _ = world
    say("усыпи рабочий ноутбук", "pc", ws)
    assert spoken[0][1] == "Усыпить рабочий ноутбук? Да или нет?"
    answer("да", "pc")
    assert [c["action"] for c in ws["mostech"].commands()] == ["power.sleep"]


def test_system_sleep_is_legacy_synonym_of_power_sleep(world):
    from sakura_core.registry import load
    decls = {d.id: d for d in load()}
    assert "system.sleep" not in decls
    assert "system:sleep" in decls["power.sleep"].legacy and decls["power.sleep"].confirm
    ws, spoken, _ = world
    say("спящий режим", "laptop", ws)
    assert spoken[0][1].startswith("Усыпить ") and st._pending_power["action"] == "power.sleep"


def test_all_pcs_lists_online(world):
    ws, spoken, _ = world
    del st.connected_devices["mostech"]
    say("выключи все компы", "laptop", ws)
    assert spoken[0][1] == "Выключить все компьютеры (игровой, ноутбук)? Да или нет?"
    answer("да", "laptop")
    assert len(ws["pc"].commands()) == len(ws["laptop"].commands()) == 1
    assert ws["mostech"].commands() == []


def test_offline_pc_is_already_off_without_question(world):
    ws, spoken, tg = world
    del st.connected_devices["laptop"]
    out = say("выключи ноутбук", "pc", ws)
    assert out == ["Ноутбук уже выключен."] and spoken == [] and not st._pending_power


def test_timeout_cancels(world, monkeypatch):
    ws, spoken, _ = world
    monkeypatch.setattr(pcm, "TTL_S", 0.05)

    async def go():
        out = []

        async def speak(phrase, listen=None):
            out.append(phrase)
        await br.v3_fast_path("выключи комп", data={"active_window": ""}, device_ws=ws["laptop"],
                              device_id="laptop", register_command=lambda a, d: "c", speak=speak,
                              source="laptop")
        await asyncio.sleep(0.3)
        return await pcm.handle_answer("да", "laptop")
    assert asyncio.run(go()) is False, "после срока «да» не выключает"
    assert spoken[-1][1] == "Отменила, ничего не выключаю."
    assert all(w.commands() == [] for w in ws.values())


def test_bye_and_offline_drop_pending(world):
    ws, spoken, _ = world
    say("выключи комп", "laptop", ws)
    assert st._pending_power
    ps.update("pc", {"type": "ping"})
    ps.mark_bye("pc", "shutdown")
    assert not st._pending_power
    assert not answer("да", "laptop")
    assert all(w.commands() == [] for w in ws.values())
    # офлайн (обрыв сокета) — то же
    say("выключи ноутбук", "mostech", ws)
    assert st._pending_power
    ps.set_offline("laptop")
    assert not st._pending_power


def test_telegram_asks_with_buttons_and_button_resolves(world):
    ws, spoken, tg = world
    out = say("выключи комп", "pc", ws, source="telegram")
    assert out == [] and spoken == []
    text, pid = tg[0]
    assert text == "Выключить игровой компьютер? Да или нет?" and pid
    assert asyncio.run(pcm.resolve("confirm", "old")) is None, "чужая кнопка не действует"
    reply = asyncio.run(pcm.resolve("confirm", pid))
    assert reply.startswith("Выключаю")
    assert [c["confirmed"] for c in ws["pc"].commands()] == [True]


def test_other_turn_drops_question(world):
    """«включи музыку» снимает вопрос; последующее «да» ничего не выключает."""
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)
    assert not answer("включи музыку", "laptop")        # не ответ — обрабатывается как обычно
    assert not st._pending_power
    assert spoken[-1][1] == "Хорошо, не выключаю."
    assert not answer("да", "laptop")
    assert all(w.commands() == [] for w in ws.values())


def test_other_turn_in_telegram_drops_question_too(world):
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)
    assert not answer("а какая погода?", "telegram")
    assert not st._pending_power and tg[-1][0] == "Хорошо, не выключаю."
    assert not answer("да", "telegram")
    assert all(w.commands() == [] for w in ws.values())


def test_yes_from_telegram_after_10_seconds_still_shuts_down(world):
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)
    st._pending_power["ts"] -= 10                       # прошло 10 с
    assert answer("да", "telegram")
    assert [c["action"] for c in ws["pc"].commands()] == ["system.shutdown"]


def test_other_question_supersedes_power_question(world):
    """Вопрос о выключении → вопрос другого диалога подтверждения → «да» → не выключается."""
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)

    async def other_question():
        br.get_router().session.expect("confirm", action="files.delete", device="laptop")
    asyncio.run(other_question())                       # Session.expect → наш вопрос снят
    assert not st._pending_power
    assert not answer("да", "laptop")                   # «да» — другому диалогу
    assert all(w.commands() == [] for w in ws.values())


def test_power_question_supersedes_older_dialogs(world):
    ws, spoken, tg = world
    br.get_router().session.expect("confirm", action="files.delete", device="laptop")
    st._pending_plan["laptop"] = {"plan": []}
    say("выключи комп", "laptop", ws)
    assert br.get_router().session.pending is None and not st._pending_plan
    assert answer("да", "laptop")
    assert ws["pc"].commands()


def test_legacy_dialog_asked_later_wins(world):
    """После нашего вопроса появилось ожидание плана (старый путь): «да» ему."""
    ws, spoken, tg = world
    say("выключи комп", "laptop", ws)
    st._pending_plan["laptop"] = {"plan": []}
    assert not answer("да", "laptop")
    assert not st._pending_power and all(w.commands() == [] for w in ws.values())


def test_proto1_clients_get_legacy_names_proto2_canonical(world):
    ws, _, _ = world
    st.device_proto.pop("pc")                           # pc — старый agent/ (proto 1)
    for phrase, legacy, canon in (("выключи комп", "system:shutdown", "system.shutdown"),
                                  ("перезагрузи игровой", "system:restart", "system.restart"),
                                  ("усыпи игровой", "system:sleep", "power.sleep")):
        ws["pc"].sent.clear(); ws["laptop"].sent.clear()
        say(phrase, "laptop", ws)
        answer("да", "laptop")
        assert ws["pc"].commands() == [{"type": "command", "action": legacy}], phrase
        st.device_proto["pc"] = 2                       # тот же ПК на proto 2
        say(phrase, "laptop", ws)
        answer("да", "laptop")
        (cmd,) = ws["pc"].commands()[-1:]
        assert cmd["action"] == canon and cmd["confirmed"] is True, phrase
        st.device_proto.pop("pc")


def test_which_computer_then_name_then_yes(world, monkeypatch):
    ws, spoken, tg = world
    del st.connected_devices["mostech"]
    monkeypatch.setattr(ps, "get_active_device", lambda: None)      # активного нет
    out = say("выключи комп", "laptop", ws)
    assert spoken[-1][1] == "Какой компьютер: игровой, ноутбук?" and spoken[-1][2] == "confirm"
    assert st._pending_power["stage"] == "which"
    assert answer("игровой", "laptop")
    assert spoken[-1][1] == "Выключить игровой компьютер? Да или нет?"
    assert all(w.commands() == [] for w in ws.values())
    assert answer("да", "laptop")
    (cmd,) = ws["pc"].commands()
    assert cmd["action"] == "system.shutdown" and cmd["confirmed"] is True
    assert ws["laptop"].commands() == []


def test_which_computer_other_answer_drops(world, monkeypatch):
    ws, spoken, tg = world
    monkeypatch.setattr(ps, "get_active_device", lambda: None)
    say("выключи комп", "laptop", ws)
    assert st._pending_power["stage"] == "which"
    assert not answer("включи музыку", "laptop")
    assert not st._pending_power and spoken[-1][1] == "Хорошо, не выключаю."
