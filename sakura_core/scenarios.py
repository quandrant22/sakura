"""Сценарии: хранение, проверка, каталог действий, сборка из фразы, исполнение.

Сценарий: {"id", "name", "enabled", "builtin", "conditions": [{"type", "value",
"days"?}], "actions": [{"type", "value", "arg"?}]} плюс служебная статистика
запусков ("last_run", "last_status", "last_detail", "run_count") — её пишет
только note_run, из клиента она не принимается.

  * действия: action (id реестра; параметр — в "arg"), pause (секунды ≤ 60),
    telegram (текст Мастеру), notify (reply kind=proactive всем master-устройствам);
  * не больше 20 шагов; action — только из реестра с обработчиком; действие
    с обязательным параметром (music.play_track …) без значения не сохраняется;
  * опасное действие (confirm в реестре) — запуск только кнопкой с confirm: true;
    голосом и автоматически такой сценарий не запускается;
  * условия (любое из них запускает сценарий): phrase — голосовая фраза;
    time — «ЧЧ:ММ» (диапазон «ЧЧ:ММ-ЧЧ:ММ» запускается в начале) и дни
    недели days (0 = пн … 6 = вс, нет — каждый день); device_connected /
    device_disconnected — id устройства ("" — любое); app_started — часть
    названия окна или игры. Автозапуск — sakura_core/scenario_triggers.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time

import config

log = logging.getLogger("sakura.scenarios")

MAX_STEPS = 20
MAX_CONDITIONS = 10
PAUSE_MAX_S = 60.0
NAME_MAX = 60
TEXT_MAX = 500
COND_TYPES = ("phrase", "time", "device_connected", "device_disconnected", "app_started")
AUTO_COND_TYPES = ("time", "device_connected", "device_disconnected", "app_started")
ACTION_TYPES = ("action", "pause", "telegram", "notify")
STAT_KEYS = ("last_run", "last_status", "last_detail", "run_count")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(-([01]\d|2[0-3]):[0-5]\d)?$")
_lock = threading.Lock()
# Сценарии, которые сейчас выполняются: второй запуск того же — отказ.
running: set[str] = set()


class ScenarioError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _path() -> str:
    return getattr(config, "SCENARIOS_PATH", "memory/scenarios.json")


def _load() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as f:
            return list(json.load(f).get("scenarios") or [])
    except (FileNotFoundError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    d = os.path.dirname(os.path.abspath(_path()))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".scenarios-", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"scenarios": items}, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, _path())


def _declarations() -> dict:
    from sakura_core.bridge import _declarations as decls
    return {d.id: d for d in decls}


def _norm(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    return " ".join(re.findall(r"[a-zа-я0-9]+", t))


def norm_time(value: str) -> str:
    """«7:30», «07.30 – 08:00» → «07:30», «07:30-08:00»."""
    v = re.sub(r"\s+", "", str(value or "")).replace("–", "-").replace("—", "-").replace(".", ":")
    out = []
    for p in v.split("-"):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", p)
        out.append(f"{int(m.group(1)):02d}:{m.group(2)}" if m else p)
    return "-".join(out)


def _split_action(value, arg) -> tuple[str, str]:
    """value «music.play_track:Кино» без arg → («music.play_track», «Кино»)."""
    v = str(value or "")
    a = "" if arg is None else str(arg)
    if not a and ":" in v:
        base, rest = v.split(":", 1)
        if base in _declarations():
            return base, rest
    return v, a


# ── проверка ──────────────────────────────────────────────────────

def validate(s: dict) -> dict:
    if not isinstance(s, dict):
        raise ScenarioError("bad_request", "сценарий — объект")
    name = s.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_MAX:
        raise ScenarioError("bad_request", f"Название: от 1 до {NAME_MAX} символов")
    conds = s.get("conditions") or []
    acts = s.get("actions") or []
    if not isinstance(conds, list) or not isinstance(acts, list):
        raise ScenarioError("bad_request", "conditions/actions — списки")
    if not acts:
        raise ScenarioError("bad_request", "Добавь хотя бы одно действие")
    if len(acts) > MAX_STEPS:
        raise ScenarioError("bad_request", f"Не больше {MAX_STEPS} действий")
    if len(conds) > MAX_CONDITIONS:
        raise ScenarioError("bad_request", f"Не больше {MAX_CONDITIONS} условий")
    decls = _declarations()
    from sakura_core.executor import get_handler
    clean_conds = []
    for i, c in enumerate(conds):
        if not isinstance(c, dict) or c.get("type") not in COND_TYPES:
            raise ScenarioError("bad_request", f"Условие {i + 1}: неизвестный тип")
        t = c["type"]
        v = str(c.get("value") or "").strip()
        out = {"type": t, "value": v}
        if t == "time":
            v = norm_time(v)
            if not _TIME.match(v):
                raise ScenarioError("bad_request", f"Условие {i + 1}: время в виде ЧЧ:ММ, например 07:30")
            out["value"] = v
            days = c.get("days")
            if days not in (None, []):
                if not isinstance(days, list) or not all(isinstance(d, int) and not isinstance(d, bool)
                                                         and 0 <= d <= 6 for d in days):
                    raise ScenarioError("bad_request", f"Условие {i + 1}: дни недели — числа 0–6")
                if len(set(days)) < 7:
                    out["days"] = sorted(set(days))
        elif t == "phrase":
            if not _norm(v):
                raise ScenarioError("bad_request", f"Условие {i + 1}: впиши фразу")
            if len(v) > 120:
                raise ScenarioError("bad_request", f"Условие {i + 1}: фраза длиннее 120 символов")
        elif t == "app_started":
            if not _norm(v):
                raise ScenarioError("bad_request", f"Условие {i + 1}: впиши название приложения или игры")
            if len(v) > 80:
                raise ScenarioError("bad_request", f"Условие {i + 1}: название длиннее 80 символов")
        elif len(v) > 80:
            raise ScenarioError("bad_request", f"Условие {i + 1}: слишком длинный id устройства")
        clean_conds.append(out)
    clean_acts = []
    for i, a in enumerate(acts):
        if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
            raise ScenarioError("bad_request", f"Действие {i + 1}: неизвестный тип")
        t = a["type"]
        if t == "action":
            v, arg = _split_action(a.get("value"), a.get("arg"))
            d = decls.get(v)
            if d is None or get_handler(v) is None:
                raise ScenarioError("bad_request", f"Действие {i + 1}: неизвестная команда {v!r}")
            arg = arg.strip()
            if d.param is not None and d.param.required != "false" and not arg:
                raise ScenarioError("bad_request",
                                    f"Действие {i + 1} («{action_title(d)}»): укажи {param_hint(d).lower()}")
            if len(arg) > 200:
                raise ScenarioError("bad_request", f"Действие {i + 1}: параметр длиннее 200 символов")
            clean_acts.append({"type": "action", "value": v, **({"arg": arg} if arg else {})})
        elif t == "pause":
            try:
                p = float(str(a.get("value")).replace(",", "."))
            except (TypeError, ValueError):
                raise ScenarioError("bad_request", f"Действие {i + 1}: пауза — число секунд") from None
            if not 0 <= p <= PAUSE_MAX_S:
                raise ScenarioError("bad_request", f"Действие {i + 1}: пауза от 0 до {PAUSE_MAX_S:.0f} секунд")
            clean_acts.append({"type": "pause", "value": f"{p:g}"})
        else:
            v = a.get("value")
            if not isinstance(v, str) or not v.strip() or len(v) > TEXT_MAX:
                raise ScenarioError("bad_request", f"Действие {i + 1}: текст от 1 до {TEXT_MAX} символов")
            clean_acts.append({"type": t, "value": v.strip()})
    return {"id": s.get("id") or None, "name": name.strip(), "enabled": bool(s.get("enabled", True)),
            "builtin": bool(s.get("builtin", False)), "conditions": clean_conds, "actions": clean_acts}


def dangerous_actions(s: dict) -> list[str]:
    decls = _declarations()
    out = []
    for a in s.get("actions", []):
        if a.get("type") != "action":
            continue
        base, _ = _split_action(a.get("value"), a.get("arg"))
        d = decls.get(base) or decls.get(str(a.get("value")))
        if d is not None and d.confirm:
            out.append(base)
    return out


def needs_device(s: dict) -> bool:
    """Есть шаг, который выполняет приложение на устройстве (executor agent)."""
    decls = _declarations()
    for a in s.get("actions", []):
        if a.get("type") == "action":
            d = decls.get(_split_action(a.get("value"), a.get("arg"))[0])
            if d is not None and d.executor == "agent":
                return True
    return False


def warnings_for(s: dict) -> list[str]:
    """Подсказки к сохранённому сценарию (не ошибки)."""
    out = []
    conds = s.get("conditions") or []
    if dangerous_actions(s) and conds:
        out.append("Есть опасные действия — сам по условию сценарий не запустится, "
                   "только кнопкой ▶ с подтверждением")
    if not conds:
        out.append(f"Условий нет — запуск кнопкой ▶ или голосом: «запусти сценарий {s.get('name', '')}»")
    if not s.get("enabled", True):
        out.append("Сценарий выключен — по условиям не запустится")
    return out


# ── каталог для конструктора ──────────────────────────────────────

GROUP_TITLES = {
    "music": "Музыка", "music_stats": "Музыка", "youtube": "YouTube", "system": "Система",
    "power": "Питание", "audio": "Звук", "display": "Экран", "window": "Окна", "close_window": "Окна",
    "app": "Приложения", "open": "Приложения", "process": "Приложения", "kettle": "Чайник",
    "reminder": "Напоминания и задачи", "task": "Напоминания и задачи", "schedule": "Расписание",
    "calendar": "Расписание", "weather": "Погода", "briefing": "Брифинг", "browser": "Браузер",
    "ext": "Браузер", "companion": "Компаньон", "game_mode": "Игры", "steam": "Игры",
    "files": "Файлы", "clipboard": "Клавиатура и буфер", "keys": "Клавиатура и буфер",
    "screenshot": "Экран", "vision": "Зрение", "ui": "Управление окнами", "net": "Сеть",
    "vps": "Сервер", "memory": "Память", "capsule": "Память", "coding": "Код",
}
GROUP_ORDER = ("Музыка", "YouTube", "Звук", "Экран", "Система", "Питание", "Приложения", "Окна",
               "Чайник", "Напоминания и задачи", "Расписание", "Погода", "Брифинг", "Игры", "Браузер",
               "Компаньон", "Файлы", "Клавиатура и буфер", "Сеть", "Зрение", "Управление окнами",
               "Память", "Сервер", "Код")
_PARAM_HINTS = {
    "query": "Что именно", "app": "Название приложения", "level": "Уровень, 0–100", "temp": "Температура, °C",
    "window": "Окно", "side": "Сторона: влево или вправо", "process": "Процесс", "text": "Текст",
    "keys": "Сочетание клавиш, например ctrl+shift+m", "file": "Файл", "element": "Элемент на экране",
    "pattern": "Что забыть", "module_name": "Название модуля", "description": "Описание",
    "filepath": "Путь к файлу", "message": "Сообщение",
}


def action_title(d) -> str:
    t = d.desc.split(" — ")[0].split(",")[0].strip()
    return (t[:1].upper() + t[1:]) if t else d.id


def param_hint(d) -> str:
    p = d.param
    if p is None:
        return ""
    if p.ask:
        return p.ask.rstrip("?").strip()
    return _PARAM_HINTS.get(p.name, p.name)


def catalog() -> list[dict]:
    """Команды реестра для выпадающего списка конструктора."""
    from sakura_core.executor import get_handler
    out = []
    for d in _declarations().values():
        if get_handler(d.id) is None:
            continue
        out.append({
            "id": d.id, "title": action_title(d), "desc": d.desc,
            "group": GROUP_TITLES.get(d.id.split(".")[0], "Другое"),
            "confirm": bool(d.confirm), "device": d.executor == "agent",
            "param": None if d.param is None else {
                "name": d.param.name, "required": d.param.required != "false", "hint": param_hint(d)},
        })
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    out.sort(key=lambda x: (order.get(x["group"], len(order)), x["title"].lower()))
    return out


# ── хранилище ─────────────────────────────────────────────────────

def list_all() -> list[dict]:
    with _lock:
        return _load()


# Встроенный «Фокус» (кнопка «Режим фокуса» в приложении): пока Мастер не
# сохранил свой вариант с этим id, запускается этот.
FOCUS_DEFAULT = {"id": "focus", "name": "Фокус", "enabled": True, "builtin": True,
                 "conditions": [{"type": "phrase", "value": "режим фокуса"}],
                 "actions": [{"type": "action", "value": "music.wave"},
                             {"type": "notify", "value": "Режим фокуса: включаю волну, не отвлекаю"}]}


def get(sid: str) -> dict | None:
    s = next((s for s in list_all() if s.get("id") == sid), None)
    if s is None and sid == FOCUS_DEFAULT["id"]:
        return json.loads(json.dumps(FOCUS_DEFAULT))
    return s


def save(s: dict) -> dict:
    clean = validate(s)
    with _lock:
        items = _load()
        old = next((x for x in items if x.get("id") == clean["id"]), None) if clean["id"] else None
        if old is None:
            clean["id"] = clean["id"] or f"s{secrets.token_hex(4)}"
            if any(x.get("id") == clean["id"] for x in items):
                raise ScenarioError("bad_request", "id занят")
            items.append(clean)
        else:
            if old.get("builtin"):
                clean["builtin"] = True
            stats = {k: old[k] for k in STAT_KEYS if k in old}
            old.clear()
            old.update(clean)
            old.update(stats)
            clean = old
        _save(items)
    return dict(clean)


def set_enabled(sid: str, enabled: bool) -> dict | None:
    with _lock:
        items = _load()
        s = next((x for x in items if x.get("id") == sid), None)
        if s is None:
            return None
        s["enabled"] = bool(enabled)
        _save(items)
        return dict(s)


def delete(sid: str) -> bool:
    with _lock:
        items = _load()
        s = next((x for x in items if x.get("id") == sid), None)
        if s is None:
            return False
        if s.get("builtin"):
            raise ScenarioError("bad_request", "встроенный сценарий не удаляется (можно выключить)")
        items.remove(s)
        _save(items)
        return True


def note_run(sid: str, status: str, detail: str = "") -> None:
    """Итог запуска: ok / error / skipped — в карточку сценария."""
    with _lock:
        items = _load()
        s = next((x for x in items if x.get("id") == sid), None)
        if s is None:
            return
        s["last_run"] = time.time()
        s["last_status"] = status
        s["last_detail"] = str(detail)[:200]
        if status != "skipped":
            s["run_count"] = int(s.get("run_count") or 0) + 1
        _save(items)


def match_phrase(text: str) -> dict | None:
    """Включённый сценарий, у которого фраза-условие совпала с текстом."""
    t = _norm(text)
    if not t:
        return None
    for s in list_all():
        if s.get("enabled") and any(c["type"] == "phrase" and _norm(c["value"]) == t
                                    for c in s.get("conditions", [])):
            return s
    return None


_RUN_CMD = re.compile(r"^(?:сакура\s+)?(?:запусти|включи|выполни|активируй)\s+сценари[йяи]\s+(.+)$")


def match_command(text: str) -> tuple[bool, dict | None]:
    """«Запусти сценарий утро» → (True, сценарий | None). Не такая команда — (False, None).
    Имя — точное совпадение, иначе единственный сценарий, чьё имя начинается так же."""
    m = _RUN_CMD.match(_norm(text))
    if not m:
        return False, None
    want = m.group(1).strip()
    items = list_all()
    exact = [s for s in items if _norm(s.get("name", "")) == want]
    if exact:
        return True, exact[0]
    prefix = [s for s in items if _norm(s.get("name", "")).startswith(want)]
    return True, (prefix[0] if len(prefix) == 1 else None)


# ── из текста (без LLM) ───────────────────────────────────────────

_SPLIT = re.compile(r"\s*(?:,|;|\bи потом\b|\bпотом\b|\bзатем\b|\bа ещё\b|\bа еще\b|\bи\b)\s*")
_PREFIX = re.compile(r"^\s*(?:сакура[,\s]+)?(?:создай|сделай|добавь|заведи)?\s*(?:новый\s+)?сценари[йя]\s*[:,—-]?\s*",
                     re.IGNORECASE)
_DAYS_WORDS = (
    (re.compile(r"\bпо будням\b|\bв будни\b", re.I), [0, 1, 2, 3, 4]),
    (re.compile(r"\bпо выходным\b|\bв выходные\b", re.I), [5, 6]),
)
_PARTS_OF_DAY = (("утром", "08:00"), ("днём", "13:00"), ("днем", "13:00"), ("вечером", "21:00"), ("ночью", "23:00"))
_TELEGRAM = re.compile(r"^(?:напиши|отправь|пришли)\s+(?:мне\s+)?(?:в\s+)?(?:телеграм\w*|телегу|tg|тг)"
                       r"\s*[:,—-]?\s*(.+)$", re.I)
_NOTIFY = re.compile(r"^(?:скажи|уведоми|покажи уведомление)\s*[:,—-]?\s*[«\"]?(.+?)[»\"]?$", re.I)
_UNTIL = r"(?=\s*(?:,|\bто\b|$))"


def _device_by_name(name: str) -> str | None:
    want = _norm(name)
    if not want:
        return None
    try:
        from sakura_core import proto_devices
        devs = proto_devices.devices()
    except Exception:
        return None
    for d in devs:
        n = _norm(d.get("name", ""))
        if want in (n, _norm(d.get("id", ""))) or (n and (want in n or n in want)):
            return d["id"]
    kinds = {"телефон": "phone", "телефона": "phone", "ноутбук": "pc", "компьютер": "pc", "пк": "pc",
             "планшет": "tablet", "наушники": "headphones"}
    kind = next((k for w, k in kinds.items() if w in want.split()), None)
    if kind:
        same = [d["id"] for d in devs if d.get("kind") == kind]
        if len(same) == 1:
            return same[0]
    return None


def _take_conditions(text: str, warnings: list[str]) -> tuple[list[dict], str]:
    """Вынуть из фразы условия запуска; вернуть их и остаток с действиями."""
    conds: list[dict] = []
    rest = text
    days = None
    for rx, ds in _DAYS_WORDS:
        if rx.search(rest):
            days = ds
            rest = rx.sub(" ", rest)
    rest = re.sub(r"\b(?:каждый день|ежедневно)\b", " ", rest, flags=re.I)
    if re.search(r"\bкаждое утро\b", rest, re.I):
        rest = re.sub(r"\bкаждое утро\b", " утром ", rest, flags=re.I)
    if re.search(r"\bкаждый вечер\b", rest, re.I):
        rest = re.sub(r"\bкаждый вечер\b", " вечером ", rest, flags=re.I)

    m = (re.search(r"\bв\s+(\d{1,2})[:.](\d{2})\b", rest)
         or re.search(r"\bв\s+(\d{1,2})\s+(утра|дня|вечера|ночи)\b", rest, re.I))
    if m:
        h, mm = int(m.group(1)), m.group(2)
        if not mm.isdigit():
            if mm.lower() in ("дня", "вечера") and h < 12:
                h += 12
            if mm.lower() == "ночи" and h == 12:
                h = 0
            mm = "00"
        if 0 <= h <= 23:
            conds.append({"type": "time", "value": f"{h:02d}:{mm}", **({"days": days} if days else {})})
        rest = rest[:m.start()] + " " + rest[m.end():]
    else:
        for word, hm in _PARTS_OF_DAY:
            if re.search(rf"\b{word}\b", rest, re.I):
                conds.append({"type": "time", "value": hm, **({"days": days} if days else {})})
                warnings.append(f"«{word}» — поставила {hm}, поправь время, если нужно")
                rest = re.sub(rf"\b{word}\b", " ", rest, flags=re.I)
                break

    def cut(rx, build):
        nonlocal rest
        mm_ = re.search(rx, rest, re.I)
        if mm_:
            c = build(mm_.group(1).strip(" «»\"'"))
            if c:
                conds.append(c)
            rest = rest[:mm_.start()] + " " + rest[mm_.end():]

    cut(r"\bкогда\s+(?:я\s+)?(?:скажу|говорю|произнесу)\s+[«\"]?([^,»\"]+)[»\"]?",
        lambda v: {"type": "phrase", "value": v})

    def dev_cond(kind):
        def build(v):
            did = _device_by_name(v)
            if did is None:
                warnings.append(f"устройство «{v}» не нашла — выбери его в списке")
            return {"type": kind, "value": did or ""}
        return build

    cut(r"\bкогда\s+(?:я\s+)?(?:подключ\w*|включ\w*|появ\w*)\s+(?:мой\s+|моя\s+)?([^,]+?)" + _UNTIL,
        dev_cond("device_connected"))
    cut(r"\bкогда\s+(?:я\s+)?(?:отключ\w*|выключ\w*|пропад\w*)\s+(?:мой\s+|моя\s+)?([^,]+?)" + _UNTIL,
        dev_cond("device_disconnected"))
    cut(r"\bкогда\s+(?:я\s+)?(?:запущу|открою|запускаю|открываю|зайду в|захожу в|запустится|откроется)"
        r"\s+([^,]+?)" + _UNTIL, lambda v: {"type": "app_started", "value": v})
    rest = re.sub(r"^\s*(?:,|\bто\b)\s*", "", re.sub(r"\s+", " ", rest).strip(), flags=re.I)
    return conds, rest.strip(" ,")


def from_text(text: str) -> tuple[dict, list[str]]:
    """Черновик сценария из фразы: условия запуска + шаги из реестра. Не сохраняется."""
    from sakura_core.bridge import get_router
    text = (text or "").strip()
    if not text:
        raise ScenarioError("bad_request", "пустая фраза")
    body = _PREFIX.sub("", text, count=1).strip() or text
    warnings: list[str] = []
    conds, rest = _take_conditions(body, warnings)
    index = get_router()._index
    actions = []
    for part in [p for p in _SPLIT.split(rest) if p and p.strip()][:MAX_STEPS]:
        part = re.sub(r"^\s*то\s+", "", part.strip(), flags=re.I)
        m = re.search(r"(?:подожди|пауза|жди)\s+(\d+)", part)
        if m:
            actions.append({"type": "pause", "value": str(max(1, min(int(m.group(1)), int(PAUSE_MAX_S))))})
            continue
        m = _TELEGRAM.match(part)
        if m:
            actions.append({"type": "telegram", "value": m.group(1).strip()})
            continue
        m_track = re.search(r"(?:включи|поставь|сыграй)\s+(?:трек|песню)\s+(.+)", part, re.IGNORECASE)
        if m_track:
            actions.append({"type": "action", "value": "music.play_track", "arg": m_track.group(1).strip()})
            continue
        hit = index.match(part, None)
        if hit is None:
            m = _NOTIFY.match(part)
            if m:
                actions.append({"type": "notify", "value": m.group(1).strip()})
                continue
            warnings.append(f"не поняла: «{part}»")
            continue
        d = hit[1]
        step = {"type": "action", "value": d.id}
        if d.param is not None:
            arg = d.param.extract(part)
            if arg:
                step["arg"] = str(arg).strip()
            elif d.param.required != "false":
                warnings.append(f"«{action_title(d)}»: укажи {param_hint(d).lower()}")
        actions.append(step)
    if not actions:
        warnings.append("ни одного действия не распознала")
    if not conds:
        warnings.append("условие не нашла — сценарий запустится кнопкой ▶; можно добавить фразу или время")
    name = re.sub(r"\s+", " ", body).strip(" .,!")
    name = (name[:1].upper() + name[1:])[:40] if name else "Новый сценарий"
    return ({"id": None, "name": name, "enabled": True, "builtin": False,
             "conditions": conds, "actions": actions}, warnings)


# ── исполнение ────────────────────────────────────────────────────

def describe_step(a: dict) -> str:
    if a.get("type") == "action":
        base, arg = _split_action(a.get("value"), a.get("arg"))
        d = _declarations().get(base)
        t = action_title(d) if d else base
        return f"{t}: {arg}" if arg else t
    if a.get("type") == "pause":
        return f"пауза {a.get('value')} с"
    return {"telegram": "Telegram", "notify": "уведомление"}.get(a.get("type"), str(a.get("type")))


async def run(s: dict, *, emit, device_ws, device_id: str, register_command,
              confirmed: bool = False, run_id: str | None = None, trigger: str = "manual") -> str:
    """Шаги по очереди; emit(event) — пуш scenario_event. Ошибка шага —
    остановка. Итог пишется в карточку сценария. Возвращает run_id."""
    from sakura_core.executor import ExecutionContext
    from sakura_core.bridge import get_executor
    run_id = run_id or f"r{secrets.token_hex(4)}"
    sid = s.get("id") or ""
    if sid:
        running.add(sid)
    final, final_detail = "ok", ""
    try:
        ex = get_executor()
        for i, a in enumerate(s["actions"][:MAX_STEPS]):
            status, detail = "ok", describe_step(a)
            try:
                if a["type"] == "action":
                    action_name, arg = _split_action(a.get("value"), a.get("arg"))
                    ctx = ExecutionContext(device_ws=device_ws, device_id=device_id,
                                           register_command=register_command,
                                           param=arg if arg else None,
                                           extra={"confirmed": confirmed, "source": device_id,
                                                  "text": f"сценарий {s['name']}",
                                                  "query": arg, "arg": arg})
                    result = await ex.execute(action_name, ctx, param=arg if arg else None)
                    if isinstance(result, tuple) and len(result) == 2:
                        if result[0]:
                            detail = str(result[0])[:200]
                        if result[1] is False:
                            status = "error"
                elif a["type"] == "pause":
                    await asyncio.sleep(min(float(a["value"]), PAUSE_MAX_S))
                elif a["type"] == "telegram":
                    from adapters.telegram import send_to_master
                    await send_to_master(a["value"])
                else:
                    from sakura_core.voice_turns import broadcast_reply
                    await broadcast_reply(a["value"], "proactive")
            except Exception as e:
                status, detail = "error", f"{type(e).__name__}: {str(e)[:120]}"
            await emit({"type": "scenario_event", "run_id": run_id, "id": sid, "step": i,
                        "status": status, "detail": detail})
            if status == "error":
                log.info(f"[scenario] {sid} run={run_id}: остановлен на шаге {i + 1}")
                final, final_detail = "error", f"шаг {i + 1}: {detail}"
                await emit({"type": "scenario_event", "run_id": run_id, "id": sid, "step": i + 1,
                            "status": "done", "detail": f"остановлено на шаге {i + 1}"})
                return run_id
        await emit({"type": "scenario_event", "run_id": run_id, "id": sid, "step": len(s["actions"]),
                    "status": "done", "detail": ""})
        log.info(f"[scenario] {sid} run={run_id} ({trigger}): выполнен ({len(s['actions'])} шагов)")
        return run_id
    finally:
        if sid:
            running.discard(sid)
            try:
                await asyncio.to_thread(note_run, sid, final, final_detail)
            except Exception as e:
                log.debug(f"[scenario] статистика {sid}: {type(e).__name__}: {e}")
