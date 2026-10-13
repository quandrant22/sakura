"""feat/pc-control: действия управления компьютером (executor: agent).

Источник правды — клиент (feat/desktop-rewrite): desktop/docs/CONTROL.md и
desktop/core/control/registry.py (ACTIONS). Проверяется: паритет id и
флагов, таблица фраз → (действие, arg), непересечение триггеров,
подтверждение опасных действий («Точно? Скажи «да».» → команда с
"confirmed": true), выбор устройства, пересказ результатов-чтений.

Run: python -m pytest tests/test_pc_control.py -q
"""

import asyncio
import json
import re
from unittest.mock import AsyncMock

import pytest

import modules.state as st
import sakura_core.bridge as br
from capabilities import pc_control as pc
from sakura_core.executor import ExecutionContext, Executor, get_handler
from sakura_core.registry import build_index, load
from sakura_core.router import Router

# desktop/core/control/registry.py ACTIONS @ feat/desktop-rewrite e892108:
# id → (reversible, confirm)
CLIENT_ACTIONS = {
    "window.minimize": (True, False), "window.maximize": (True, False),
    "window.restore": (True, False), "window.snap": (True, False),
    "window.move_monitor": (True, False), "window.focus": (True, False),
    "window.list": (True, False), "power.lock": (True, False),
    "power.sleep": (False, True), "power.display_off": (True, False),
    "process.list": (True, False), "process.kill": (False, True),
    "clipboard.read": (True, False), "clipboard.write": (False, False),
    "clipboard.clear": (False, False), "display.brightness": (True, False),
    "display.night_light": (True, False), "audio.mic_mute": (True, False),
    "net.wifi": (True, True), "net.bluetooth": (True, False),
    "keys.type": (False, False), "keys.hotkey": (False, False),
    "keys.media": (True, False), "ui.click": (False, False),
    "ui.type": (False, False), "ui.scroll": (True, False), "ui.read": (True, False),
    "files.open": (True, False), "files.reveal": (True, False),
    "files.recent": (True, False), "files.copy": (True, False),
    "files.move": (False, True), "files.delete": (True, True),
}
DANGEROUS = {"power.sleep", "process.kill", "net.wifi", "files.move", "files.delete"}


@pytest.fixture(scope="module")
def decls():
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    return {d.id: d for d in load()}


@pytest.fixture(scope="module")
def index(decls):
    return build_index(decls.values())


# ── паритет с клиентом ─────────────────────────────────────────────

def test_every_client_action_declared_with_client_flags(decls):
    for aid, (reversible, confirm) in CLIENT_ACTIONS.items():
        assert aid in decls, aid
        d = decls[aid]
        assert d.executor == "agent", aid
        if aid == "files.open":
            continue      # был до pc-control: confirm совпадает, параметр — open_file:<имя>
        assert (d.reversible, d.confirm) == (reversible, confirm), aid
        assert 3 <= len(d.triggers) <= 6, (aid, d.triggers)
        assert d.followup in ("ack", "llm"), aid
        assert get_handler(aid) is not None, aid


def test_dangerous_confirm_and_prompt(decls):
    assert {a for a in CLIENT_ACTIONS if decls[a].confirm} == DANGEROUS
    for aid in DANGEROUS:
        assert decls[aid].confirm_prompt.endswith("Точно? Скажи «да».")


def test_no_audio_output_and_read_actions_follow_llm(decls):
    assert "audio.output" not in decls
    for aid in pc.READ_ACTIONS:
        assert decls[aid].followup == "llm", aid


# ── таблица фраз → действие и arg ──────────────────────────────────

PHRASES = [
    ("сверни окно", "window.minimize", ""),
    ("сверни окно телеграм", "window.minimize", "телеграм"),
    ("спрячь окно", "window.minimize", ""),
    ("разверни окно", "window.maximize", ""),
    ("разверни хром на весь экран", "window.maximize", "хром"),
    ("окно на весь экран", "window.maximize", ""),
    ("восстанови окно", "window.restore", ""),
    ("верни окно как было", "window.restore", ""),
    ("прижми окно влево", "window.snap", "left"),
    ("окно вправо", "window.snap", "right"),
    ("окно наверх", "window.snap", "top"),
    ("перекинь окно на второй монитор", "window.move_monitor", "2"),
    ("перенеси окно на другой монитор", "window.move_monitor", "next"),
    ("окно на второй монитор", "window.move_monitor", "2"),
    ("покажи окно телеграм", "window.focus", "телеграм"),
    ("активируй окно блокнот", "window.focus", "блокнот"),
    ("какие окна открыты", "window.list", ""),
    ("список окон", "window.list", ""),
    ("заблокируй сессию", "power.lock", ""),
    ("заблокируй ноутбук", "power.lock", ""),
    ("выключи экран", "power.display_off", ""),
    ("погаси монитор", "power.display_off", ""),
    ("усыпи компьютер", "power.sleep", ""),
    ("отправь компьютер в сон", "power.sleep", ""),
    ("что жрёт память", "process.list", ""),
    ("что жрет память", "process.list", ""),
    ("список процессов", "process.list", ""),
    ("закрой процесс блокнот", "process.kill", "блокнот"),
    ("убей процесс chrome.exe", "process.kill", "chrome.exe"),
    ("останови процесс 4312", "process.kill", "4312"),
    ("что в буфере обмена", "clipboard.read", ""),
    ("прочитай буфер обмена", "clipboard.read", ""),
    ("скопируй в буфер адрес почты", "clipboard.write", "адрес почты"),
    ("положи в буфер обмена привет", "clipboard.write", "привет"),
    ("очисти буфер обмена", "clipboard.clear", ""),
    ("яркость на 70", "display.brightness", "70"),
    ("поставь яркость 30", "display.brightness", "30"),
    ("яркость на пятьдесят", "display.brightness", "50"),
    ("включи ночной свет", "display.night_light", "on"),
    ("выключи ночной свет", "display.night_light", "off"),
    ("выключи микрофон", "audio.mic_mute", "on"),
    ("включи микрофон", "audio.mic_mute", "off"),
    ("заглуши микрофон", "audio.mic_mute", "on"),
    ("выключи вайфай", "net.wifi", "off"),
    ("включи вайфай", "net.wifi", "on"),
    ("включи блютуз", "net.bluetooth", "on"),
    ("выключи bluetooth", "net.bluetooth", "off"),
    ("напечатай привет мир", "keys.type", "привет мир"),
    ("введи текст пароль не скажу", "keys.type", "пароль не скажу"),
    ("нажми контрол це", "keys.hotkey", "ctrl+c"),
    ("нажми сочетание контрол шифт эс", "keys.hotkey", "ctrl+shift+s"),
    ("нажми альт таб", "keys.hotkey", "alt+tab"),
    ("следующий трек клавишей", "keys.media", "next"),
    ("пауза клавишей", "keys.media", "play_pause"),
    ("тише клавишей", "keys.media", "volume_down"),
    ("покажи файл отчёт в проводнике", "files.reveal", "отчёт"),
    ("где лежит файл договор", "files.reveal", "договор"),
    ("недавние файлы", "files.recent", ""),
    ("какие файлы я открывал", "files.recent", ""),
    ("скопируй файл отчёт на диск D", "files.copy", "отчёт|диск D"),
    ("перенеси файл отчёт в документы", "files.move", "отчёт|документы"),
    ("перемести документ смета в архив", "files.move", "смета|архив"),
    ("удали файл черновик", "files.delete", "черновик"),
    ("отправь в корзину файл старый план", "files.delete", "старый план"),
    ("нажми кнопку сохранить", "ui.click", "сохранить"),
    ("кликни на отправить", "ui.click", "отправить"),
    ("впиши в поиск котики", "ui.type", "поиск|котики"),
    ("впиши привет", "ui.type", "привет"),
    ("прокрути окно вниз на три страницы", "ui.scroll", "down:3"),
    ("пролистай список вверх", "ui.scroll", "up"),
    ("прочитай окно", "ui.read", ""),
    ("что написано в окне", "ui.read", ""),
]


async def _no_llm(text, catalog):
    return None


def _route(text):
    router = Router(llm_classify=_no_llm)
    return asyncio.run(router.route(text, None))


def _arg(action, text, param):
    cmd = get_handler(action)(ExecutionContext(param=param, extra={"text": text}))
    return cmd.action, cmd.arg


def test_phrase_table_size():
    assert len(PHRASES) >= 60
    assert {a for _, a, _ in PHRASES} >= set(CLIENT_ACTIONS) - {"files.open"}


@pytest.mark.parametrize("text,action,arg", PHRASES)
def test_phrase_routes_to_action_with_client_arg(decls, text, action, arg):
    d = _route(text)
    assert d.action == action, (text, d.action, d.source)
    assert d.source.startswith("registry"), d.source
    wire, got = _arg(action, text, d.param)
    assert wire == action and got == arg, (text, got)


def test_new_triggers_route_to_own_action(decls, index):
    """Каждый новый триггер (и «Сакура, …») выигрывает у старых самым
    длинным совпадением — пересечений нет."""
    for aid in CLIENT_ACTIONS:
        if aid == "files.open":
            continue
        for t in decls[aid].triggers:
            for phrase in (t, f"сакура, {t}"):
                m = index.match(phrase, None)
                assert m is not None and m[1].id == aid, (phrase, m and m[1].id)


def test_new_triggers_not_inside_old_triggers(decls):
    new = {a for a in CLIENT_ACTIONS if a != "files.open"}
    old = {i: d for i, d in decls.items() if i not in new}
    for aid in new:
        for t in decls[aid].triggers:
            rx = re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)
            for oid, od in old.items():
                for ot in od.triggers:
                    assert not rx.search(ot), (aid, t, oid, ot)


def test_old_lock_and_sleep_untouched(decls):
    """system.lock / system.sleep — для старого agent/: фразы на месте."""
    assert _route("заблокируй компьютер").action == "system.lock"
    assert _route("спящий режим").action == "system.sleep"
    assert _route("переключись на телеграм").action == "app.switch"


@pytest.mark.parametrize("spoken,keys", [
    ("контрол це", "ctrl+c"), ("ctrl+shift+esc", "ctrl+shift+esc"),
    ("альт ф4", "alt+f4"), ("вин д", "win+д"),
])
def test_hotkey_normalization(spoken, keys):
    assert pc.hotkey_arg(spoken) == keys


def test_required_params_raise_without_value():
    for aid in ("process.kill", "net.wifi", "files.move", "keys.hotkey"):
        with pytest.raises(ValueError):
            get_handler(aid)(ExecutionContext(param=None, extra={"text": "что-то"}))


# ── подтверждение опасных действий ─────────────────────────────────

class AgentWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    def commands(self):
        return [m for m in self.sent if m.get("type") == "command"]


@pytest.fixture
def engine(monkeypatch, decls):
    router = Router(declarations=list(decls.values()), llm_classify=_no_llm)
    executor = Executor(session=router.session, declarations=list(decls.values()))
    monkeypatch.setattr(br, "get_router", lambda: router)
    monkeypatch.setattr(br, "get_executor", lambda: executor)
    ids = iter(f"cmd{i}" for i in range(100))
    return router, executor, (lambda action, device: next(ids))


def _fast(text, ws, device, reg, source=None, speak=None):
    return asyncio.run(br.v3_fast_path(
        text, data={"active_window": ""}, device_ws=ws, device_id=device,
        register_command=reg, speak=speak, source=source or device))


def _yes(text, source, ws, device, reg):
    router = br.get_router()
    decision = asyncio.run(router.route(text, None, source=source))
    if decision.verdict != "confirm":
        return decision, None
    return decision, asyncio.run(br.execute_decision(
        decision, device_ws=ws, device_id=device, register_command=reg,
        text=text, source=source))


@pytest.mark.parametrize("text,action,arg", [
    ("усыпи компьютер", "power.sleep", ""),
    ("закрой процесс блокнот", "process.kill", "блокнот"),
    ("выключи вайфай", "net.wifi", "off"),
    ("перенеси файл отчёт в документы", "files.move", "отчёт|документы"),
    ("удали файл черновик", "files.delete", "черновик"),
])
def test_dangerous_asks_then_sends_confirmed(engine, decls, text, action, arg):
    _, _, reg = engine
    ws = AgentWS()
    spoken = []

    async def speak(phrase, listen=None):
        spoken.append(phrase)
    assert _fast(text, ws, "laptop", reg, speak=speak)
    assert ws.commands() == [], "без «да» команда не уходит"
    assert spoken == [decls[action].confirm_prompt]

    decision, (ok, cmd_id) = _yes("да", "laptop", ws, "laptop", reg)
    assert ok and cmd_id
    (cmd,) = ws.commands()
    assert cmd["action"] == action and cmd["confirmed"] is True
    assert cmd.get("arg", "") == arg, "параметр из исходной фразы, а не из «да»"


def test_safe_action_has_no_confirmed_flag(engine):
    _, _, reg = engine
    ws = AgentWS()
    assert _fast("сверни окно", ws, "laptop", reg)
    (cmd,) = ws.commands()
    assert "confirmed" not in cmd and cmd["action"] == "window.minimize"


def test_yes_from_other_device_is_not_accepted(engine):
    _, _, reg = engine
    ws = AgentWS()
    _fast("усыпи компьютер", ws, "laptop", reg, speak=AsyncMock())
    decision, res = _yes("да", "pc", ws, "pc", reg)
    assert decision.verdict == "wrong_source" and res is None
    assert ws.commands() == []


def test_no_answers_deny(engine):
    _, _, reg = engine
    ws = AgentWS()
    _fast("закрой процесс блокнот", ws, "laptop", reg, speak=AsyncMock())
    decision, res = _yes("нет", "laptop", ws, "laptop", reg)
    assert decision.verdict == "deny" and ws.commands() == []


def test_executor_payload_confirmed_only_when_confirmed():
    from sakura_core.executor import AgentCommand
    ws = AgentWS()
    send = Executor._default_send
    asyncio.run(send(AgentCommand("net.wifi", arg="off"),
                     ExecutionContext(device_ws=ws, extra={"confirmed": True})))
    asyncio.run(send(AgentCommand("net.wifi", arg="off"),
                     ExecutionContext(device_ws=ws, extra={})))
    assert ws.sent[0]["confirmed"] is True and "confirmed" not in ws.sent[1]


def test_voice_yes_goes_through_executor_and_arms_ack(engine, monkeypatch):
    """Голос: «да» на process.kill — команда с confirmed и arg, подтверждение
    вооружено; старый путь execute_critical_action не трогается."""
    import adapters.ws as wh
    import modules.acks as acks
    import sakura_core.executor as ex
    from tests.test_turn_end import FakeWS, _data, _mk_ctx, _setup
    from sakura_core.router import Decision
    ws = FakeWS()
    real_execute = br.execute_decision
    _setup(monkeypatch, ws, decision=Decision(None, "conversation"))
    router, executor, reg = engine
    monkeypatch.setattr(br, "get_router", lambda: router)
    monkeypatch.setattr(br, "execute_decision", real_execute)
    crit = AsyncMock()
    monkeypatch.setattr(ex, "execute_critical_action", crit)
    armed = []
    monkeypatch.setattr(acks, "arm", lambda cmd_id, **kw: armed.append((cmd_id, kw["action"])))
    ctx = _mk_ctx(AsyncMock())
    ctx["_register_command"] = reg
    # 1) вопрос
    _fast("закрой процесс блокнот", ws, "laptop", reg, speak=AsyncMock())
    # 2) «да» голосом через настоящий обработчик
    asyncio.run(wh.handle_voice_command(None, _data("да"), ctx))
    cmds = [m for m in ws.sent if m.get("type") == "command"]
    assert cmds == [{"type": "command", "action": "process.kill", "id": cmds[0]["id"],
                     "arg": "блокнот", "confirmed": True}]
    crit.assert_not_awaited()
    assert armed == [(cmds[0]["id"], "process.kill")]


# ── устройство ─────────────────────────────────────────────────────

@pytest.fixture
def devices(monkeypatch):
    saved = dict(st.connected_devices)
    st.connected_devices.clear()
    yield st.connected_devices
    st.connected_devices.clear()
    st.connected_devices.update(saved)


def test_work_laptop_phrase_targets_mostech(engine, devices):
    _, _, reg = engine
    here, work = AgentWS(), AgentWS()
    devices.update({"laptop": here, "mostech": work})
    assert _fast("сверни окно на рабочем ноутбуке", here, "laptop", reg)
    assert here.commands() == []
    (cmd,) = work.commands()
    assert cmd["action"] == "window.minimize" and cmd.get("arg", "") == ""


def test_work_laptop_dangerous_yes_from_asking_device(engine, devices):
    _, _, reg = engine
    here, work = AgentWS(), AgentWS()
    devices.update({"laptop": here, "mostech": work})
    _fast("закрой процесс блокнот на рабочем ноутбуке", here, "laptop", reg,
          speak=AsyncMock())
    decision, (ok, _) = _yes("да", "laptop", work, "mostech", reg)
    assert ok
    (cmd,) = work.commands()
    assert cmd["arg"] == "блокнот" and cmd["confirmed"] is True


def test_work_laptop_offline(engine, devices):
    _, _, reg = engine
    here = AgentWS()
    devices.update({"laptop": here})
    said = []

    async def speak(p, listen=None):
        said.append(p)
    assert _fast("сверни окно на рабочем ноутбуке", here, "laptop", reg, speak=speak)
    assert said == ["Рабочий ноутбук сейчас не в сети."] and here.commands() == []


def test_default_device_is_focused(engine):
    _, _, reg = engine
    ws = AgentWS()
    _fast("выключи экран", ws, "laptop", reg)
    assert ws.commands()[0]["action"] == "power.display_off"


# ── пересказ результатов-чтений ────────────────────────────────────

def test_read_result_retold_by_voice(monkeypatch, devices):
    import modules.tts_server as tts
    import sakura_core.ws_protocol as wp
    from sakura_core import voice_turns
    from tests.test_turn_end import FakeWS
    ws = FakeWS()
    devices["laptop"] = ws
    spoken = []

    async def _speak(text, websocket, device_id, **kw):
        spoken.append(text)
    monkeypatch.setattr(wp, "stream_tts_to_device", _speak)
    monkeypatch.setattr(st, "_pending_commands", {})
    ask = AsyncMock(return_value="Открыты телеграм и браузер.")
    ctx = {"ask_gemini": ask, "bot": AsyncMock(), "_resolve_command_status": lambda *a: None}

    async def _go():
        async def _turn():
            st._pending_commands["w1"] = {"action": "window.list", "device": "laptop",
                                          "ts": 0.0, "status": "sent",
                                          "turn": voice_turns.current()}
        await voice_turns.start("laptop", ws, _turn).task
        await wp.handle_command_result(None, {
            "type": "command_result", "id": "w1", "device_id": "laptop", "ok": True,
            "status": "done", "detail": "Открытые окна: Telegram; Opera"}, ctx)
    asyncio.run(_go())
    assert spoken == ["Открыты телеграм и браузер."]
    prompt = ask.await_args.args[0]
    assert "Открытые окна: Telegram; Opera" in prompt and "Какие окна открыты" in prompt
