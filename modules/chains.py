"""
modules/chains.py — Цепочки действий (бэклог №18) и градиент автономии (бэклог №19).

№18: «Подготовь к стриму» = OBS + Yandex Music + тихий режим.
     Цепочки команд, которые Сакура выполняет последовательно.

№19: Градиент автономии — три уровня:
  "auto"    — выполняет без спроса (системное управление, музыка)
  "confirm" — сначала спрашивает Мастера (удаление файлов, отправка сообщений)
  "deny"    — никогда не делает без явного разрешения

Интеграция в main.py:
  from modules.chains import parse_chain, run_chain, AUTONOMY_LEVEL
  chain = parse_chain(text)
  if chain:
      result = await run_chain(chain, connected_devices, ws, ask_gemini_fn)
"""

import json
import logging
import os
import re
from typing import Optional

log = logging.getLogger("sakura.chains")

CUSTOM_CHAINS_FILE = "memory/custom_chains.json"
VOICE_TRIGGERS_FILE = "memory/voice_triggers.json"


# ── Градиент автономии (бэклог №19) ─────────────────────────────────

AUTONOMY_LEVEL = {
    # auto — делает сама
    "volume":          "auto",
    "music":           "auto",
    "screenshot":      "auto",
    "open_app":        "auto",
    "open_url":        "auto",
    "open_youtube":    "auto",
    "close_window":    "auto",
    "browser":         "auto",

    # confirm — спрашивает сначала
    "delete_file":     "confirm",
    "send_message":    "confirm",
    "send_email":      "confirm",
    "modify_file":     "confirm",
    "system_shutdown": "confirm",
    "system_restart":  "confirm",

    # deny — только по явному разрешению Мастера через rules.py
    "access_passwords": "deny",
    "access_banking":   "deny",
    "wipe_memory":      "deny",
}


def check_autonomy(action_type: str) -> str:
    """
    Возвращает уровень автономии для типа действия.
    "auto" / "confirm" / "deny"

    Порядок поиска:
      1. Полная строка ("volume:50" → "volume:50")
      2. Ключ до ":" ("volume:50" → "volume")
      3. Первое слово до "_" ("delete_file" → "delete_file", затем "delete")
    """
    # 1. Ключ до ":" (без значения)
    key = action_type.split(":")[0]
    if key in AUTONOMY_LEVEL:
        return AUTONOMY_LEVEL[key]
    # 2. Первое слово до "_" (напр. "send" из "send_message")
    short = key.split("_")[0]
    return AUTONOMY_LEVEL.get(short, "auto")


# ── Предустановленные цепочки ────────────────────────────────────────

_PRESET_CHAINS: dict[str, list[dict]] = {
    "стрим": [
        {"action": "open_app:obs",            "label": "открыть OBS",         "delay": 2.0},
        {"action": "music:wave",              "label": "включить свою волну",  "delay": 0.5},
        {"action": "volume:40",               "label": "громкость 40%",        "delay": 0.0},
        {"action": "say:Стрим готов.",        "label": "озвучить",             "delay": 0.0},
    ],
    "работа": [
        {"action": "open_app:code",           "label": "открыть VS Code",      "delay": 1.5},
        {"action": "open_app:chrome",         "label": "открыть браузер",      "delay": 0.5},
        {"action": "volume:25",               "label": "громкость 25%",        "delay": 0.0},
    ],
    "игра": [
        {"action": "volume:60",               "label": "громкость 60%",        "delay": 0.0},
        {"action": "open_app:steam",          "label": "открыть Steam",        "delay": 2.0},
    ],
    "ночь": [
        {"action": "volume:15",               "label": "громкость 15%",        "delay": 0.0},
        {"action": "music:wave",              "label": "тихая музыка",         "delay": 0.5},
        {"action": "say:Спокойной ночи.",     "label": "пожелать спокойной",   "delay": 0.0},
    ],
    "тишина": [
        {"action": "volume:0",                "label": "выключить звук",       "delay": 0.0},
        {"action": "music:play_pause",        "label": "пауза музыки",         "delay": 0.3},
    ],
}

# Паттерны для детекта запроса цепочки
_CHAIN_TRIGGERS = {
    "стрим":  re.compile(r"(подготовь|запусти|настрой).{0,15}(стрим|stream)", re.I),
    "работа": re.compile(r"(подготовь|запусти|настрой).{0,15}(рабоч|работ)", re.I),
    "игра":   re.compile(r"(подготовь|запусти|режим).{0,10}(игр)", re.I),
    "ночь":   re.compile(r"(ночной режим|готов.{0,5}ко сну|спать)", re.I),
    "тишина": re.compile(r"(тихий режим|тишина|не мешай|созвон начинается)", re.I),
}


# ── Парсинг ──────────────────────────────────────────────────────────

def parse_chain(text: str) -> Optional[dict]:
    """
    Проверяет, является ли text запросом цепочки.
    Сначала проверяет предустановленные, потом пользовательские.
    Возвращает {"name": str, "steps": list} или None.
    """
    tl = text.lower().strip()
    # Предустановленные
    for name, pattern in _CHAIN_TRIGGERS.items():
        if pattern.search(tl):
            return {"name": name, "steps": _PRESET_CHAINS[name]}
    # Пользовательские
    custom = get_custom_chain(tl)
    if custom:
        return custom
    return None


# ── Исполнение ───────────────────────────────────────────────────────

async def run_chain(
    chain: dict,
    connected_devices: dict,
    ask_gemini_fn,
    stream_tts_fn,
    device_id: str = "laptop",
) -> str:
    """
    Выполняет цепочку действий.
    Возвращает строку-отчёт для Мастера.
    """
    import asyncio

    name  = chain["name"]
    steps = chain["steps"]
    ws    = connected_devices.get(device_id)

    log.info(f"[chains] Запускаю цепочку '{name}' ({len(steps)} шагов)")

    done  = []
    fails = []

    for step in steps:
        action = step["action"]
        label  = step.get("label", action)
        delay  = step.get("delay", 0.3)

        autonomy = check_autonomy(action)
        if autonomy == "deny":
            log.warning(f"[chains] Шаг '{label}' запрещён уровнем автономии")
            fails.append(label)
            continue

        # say: — TTS прямо здесь, не через устройство
        if action.startswith("say:") and ws:
            phrase = action[4:]
            try:
                await stream_tts_fn(phrase, ws, device_id, literal=True)
                done.append(label)
            except Exception as e:
                log.error(f"[chains] TTS error: {e}")
                fails.append(label)
        elif ws:
            try:
                await ws.send(json.dumps({"type": "command", "action": action}))
                done.append(label)
            except Exception as e:
                log.error(f"[chains] WS send error: {e}")
                fails.append(label)
        else:
            log.warning(f"[chains] Устройство {device_id} оффлайн, шаг '{label}' пропущен")
            fails.append(label + " (офлайн)")

        if delay > 0:
            await asyncio.sleep(delay)

    # Генерируем ответ
    if not fails:
        prompt = f"Цепочка '{name}' выполнена: {', '.join(done)}. Скажи одну фразу — коротко."
    else:
        prompt = (
            f"Цепочка '{name}': выполнено {', '.join(done) or 'ничего'}. "
            f"Не удалось: {', '.join(fails)}. Скажи коротко что сделала и что нет."
        )

    reply = await ask_gemini_fn(prompt, save_history=False)
    return reply or f"Цепочка '{name}' выполнена."


# ── Динамические цепочки из промпта Мастера ─────────────────────────

async def parse_chain_from_llm(text: str, ask_gemini_fn) -> Optional[dict]:
    """
    Если текст выглядит как сложная составная команда,
    просим LLM разложить её на шаги.
    Это расширяемая точка — пока используем только для неизвестных цепочек.
    """
    # Признаки составной команды: союзы и перечисления
    compound_hints = (
        " и потом", " затем", " после этого", " а потом", " и ещё",
        " и открой", " и включи", " и поставь"
    )
    tl = text.lower()
    if not any(h in tl for h in compound_hints):
        return None

    # Слишком простые — пропускаем
    words = len(text.split())
    if words < 5:
        return None

    try:
        from config import get_active_key, mark_key_used
        from google import genai
        from google.genai import types

        key = get_active_key()
        if not key:
            return None

        prompt = (
            f"Команда Мастера: «{text}»\n\n"
            "Если это несколько последовательных действий с устройством — "
            "разложи на шаги. Каждый шаг: action (из списка: "
            "open_app:<имя>, volume:<0-100>, music:wave, music:play_pause, "
            "open_url:<url>, screenshot:, say:<фраза>) и delay (секунды).\n"
            "Верни JSON: {\"steps\": [{\"action\": \"...\", \"label\": \"...\", \"delay\": 0.5}]}\n"
            "Если это НЕ последовательность действий — верни {\"steps\": []}"
        )

        client = genai.Client(api_key=key)
        r = await __import__("asyncio").to_thread(
            client.models.generate_content,
            model    = "gemini-3.1-flash-lite",
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        raw = (r.text or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        mark_key_used(key)

        steps = data.get("steps", [])
        if not steps:
            return None

        return {"name": "динамическая", "steps": steps}

    except Exception as e:
        log.debug(f"[chains] LLM-парсинг не удался: {e}")
        return None


# ── Пользовательские цепочки ───────────────────────────────────────

def _load_custom_chains() -> dict:
    if os.path.exists(CUSTOM_CHAINS_FILE):
        with open(CUSTOM_CHAINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_custom_chains(chains: dict):
    os.makedirs(os.path.dirname(CUSTOM_CHAINS_FILE), exist_ok=True)
    with open(CUSTOM_CHAINS_FILE, "w", encoding="utf-8") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)


def add_custom_chain(name: str, steps: list[dict]):
    """Добавляет пользовательскую цепочку."""
    chains = _load_custom_chains()
    chains[name.lower()] = {"name": name, "steps": steps}
    _save_custom_chains(chains)
    log.info(f"[chains] добавлена цепочка '{name}' ({len(steps)} шагов)")


def get_custom_chain(name: str) -> dict | None:
    """Ищет пользовательскую цепочку по имени."""
    chains = _load_custom_chains()
    return chains.get(name.lower())


def list_custom_chains() -> str:
    """Список пользовательских цепочек."""
    chains = _load_custom_chains()
    if not chains:
        return "Нет пользовательских цепочек."
    lines = [f"• {name} ({len(c['steps'])} шагов)" for name, c in chains.items()]
    return "Пользовательские цепочки:\n" + "\n".join(lines)


def delete_custom_chain(name: str) -> bool:
    """Удаляет пользовательскую цепочку."""
    chains = _load_custom_chains()
    if name.lower() in chains:
        del chains[name.lower()]
        _save_custom_chains(chains)
        return True
    return False


# ── Голосовые триггеры ─────────────────────────────────────────────

def _load_triggers() -> list[dict]:
    if os.path.exists(VOICE_TRIGGERS_FILE):
        with open(VOICE_TRIGGERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_triggers(triggers: list[dict]):
    os.makedirs(os.path.dirname(VOICE_TRIGGERS_FILE), exist_ok=True)
    with open(VOICE_TRIGGERS_FILE, "w", encoding="utf-8") as f:
        json.dump(triggers, f, ensure_ascii=False, indent=2)


def add_voice_trigger(phrase: str, actions: list[dict], timeout: int = 0):
    """
    Добавляет голосовой триггер.
    phrase: фраза-триггер ("стоп")
    actions: список действий [{"action": "music:play_pause"}, {"action": "say:Поняла"}]
    timeout: молчать N секунд после срабатывания (0 = без ограничения)
    """
    triggers = _load_triggers()
    triggers.append({
        "id": int(__import__("time").time() * 1000),
        "phrase": phrase.lower(),
        "actions": actions,
        "timeout": timeout,
    })
    _save_triggers(triggers)
    log.info(f"[chains] добавлен триггер '{phrase}' ({len(actions)} действий)")


def match_voice_trigger(text: str) -> dict | None:
    """Проверяет, срабатывает ли голосовой триггер."""
    tl = text.lower().strip().rstrip(".?!")
    triggers = _load_triggers()
    for t in triggers:
        if tl == t["phrase"] or tl.startswith(t["phrase"]):
            return t
    return None


def list_voice_triggers() -> str:
    """Список голосовых триггеров."""
    triggers = _load_triggers()
    if not triggers:
        return "Нет голосовых триггеров."
    lines = []
    for t in triggers:
        actions_str = ", ".join(a.get("action", "?") for a in t["actions"])
        lines.append(f"• «{t['phrase']}» → {actions_str}")
    return "Голосовые триггеры:\n" + "\n".join(lines)


def delete_voice_trigger(trigger_id: int) -> bool:
    """Удаляет голосовой триггер по ID."""
    triggers = _load_triggers()
    before = len(triggers)
    triggers = [t for t in triggers if t["id"] != trigger_id]
    if len(triggers) < before:
        _save_triggers(triggers)
        return True
    return False
