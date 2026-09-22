"""Реестр способностей Сакуры v3 — единственный источник правды.

Читает core/capabilities.yaml, валидирует (падать на старте, а не в бою),
строит индекс триггеров и собирает каталог для LLM (замена INTENTS_PROMPT).

Правила матчинга — часть контракта (см. шапку capabilities.yaml):
  1. только по границам слов: (?<!\\w) / (?!\\w), не \\b — как в
     core/state.py:check_confirmation;
  2. выигрывает САМЫЙ ДЛИННЫЙ совпавший триггер, не первый по порядку;
  3. декларации с context участвуют в матчинге только при совпадении контекста.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

log = logging.getLogger("sakura.registry")

REGISTRY_PATH = Path(__file__).resolve().parent / "capabilities.yaml"

EXECUTORS = ("vps", "agent")
CONTEXTS = ("playing:music", "window:youtube", "window:browser")
# followup — что следует за исполнением действия:
#   ack — кроме «Готово» ничего не звучит (модель не зовётся);
#   llm — «Готово» не звучит, ответ придёт от command_result.
# Знание лежит здесь, а не в двух местах (находка: мост говорил «Готово»
# всегда, а command_result решал по своему захардкоженному списку).
FOLLOWUPS = ("ack", "llm")
# resolve — источник значений параметра (Param.resolve). Пока один:
# installed_apps — параметр должен оказаться установленным приложением.
# Список присылает агент (apps_list после каждой регистрации), сервер
# держит его в памяти (set_installed_apps / installed_apps ниже).
# Зачем: однословные «открой/покажи» без фильтра перехватывали
# «покажи погоду» раньше LLM и рапортовали «Готово» (followup: ack).
PARAM_RESOLVES = ("installed_apps",)
REQUIRED_FIELDS = ("id", "desc", "executor", "reversible", "confirm", "triggers",
                   "followup")

# Действия, у которых намеренно нет исполнения. С этапа 7 список пуст:
# развязаны последние восемь id (coding.*, files.open, calendar.list), у
# каждого id реестра есть хендлер, и validate(require_handlers=True) это
# проверяет. Список оставлен как явный escape hatch: осознанное исключение
# должно быть видимым, а не молчаливым (находка этапа 6 — 13 id не
# исполнялись, мост возвращал (False, None), и никто этого не видел).
KNOWN_UNREACHABLE: frozenset[str] = frozenset()


class RegistryError(Exception):
    """Нарушение контракта реестра. Падать на старте, а не в бою."""


@dataclass(frozen=True)
class Param:
    """Параметр, извлекаемый из текста пользователя.

    pattern - regex с одной группой захвата.
    Извлекает значение из полного текста фразы пользователя.
    Поддерживает словесные числа (пятьдесят → 50) для.temperature.
    """

    name: str
    pattern: str
    required: str = "true"  # "true" | "false" | "ask"
    # resolve — ограничение источника значения (см. PARAM_RESOLVES).
    # "installed_apps": значение должно оказаться установленным приложением,
    # иначе декларация не матчится. None — фильтра нет (однозначные
    # триггеры вроде «переключись на» фильтровать не нужно).
    resolve: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.required, bool):
            object.__setattr__(self, "required", "true" if self.required else "false")

    def extract(self, text: str) -> Optional[str]:
        """Извлечь значение параметра из текста. None если не найдено."""
        m = re.search(self.pattern, text, re.IGNORECASE)
        if not m:
            # Попытка: словесные числа после «до»/«на»
            m = re.search(r"(?:до|на)\s+([а-яё]+)", text.lower())
            if m:
                word = m.group(1)
                digit = _WORD_DIGITS.get(word)
                if digit:
                    return digit
            return None
        # Используем первую непустую группу захвата
        for g in m.groups():
            if g is not None:
                # Проверяем, не словесное ли число
                digit = _WORD_DIGITS.get(g.lower())
                if digit:
                    return digit
                return g
        return None


# Словесные числа → digits (именительный + родительный падежи)
_WORD_DIGITS: dict[str, str] = {
    "ноль": "0", "десять": "10", "двадцать": "20", "тридцать": "30",
    "сорок": "40", "сорока": "40",
    "пятьдесят": "50", "пятидесяти": "50",
    "шестьдесят": "60", "шестидесяти": "60",
    "семьдесят": "70", "семидесяти": "70",
    "восемьдесят": "80", "восьмидесяти": "80",
    "девяносто": "90", "девяноста": "90",
    "сто": "100",
}


@dataclass(frozen=True)
class Declaration:
    """Одна способность: канонический id, описание, исполнитель, триггеры."""

    id: str
    desc: str
    executor: str
    reversible: bool
    confirm: bool
    triggers: tuple[str, ...]
    followup: str = "ack"
    legacy: tuple[str, ...] = ()
    context: Optional[str] = None
    param: Optional[Param] = None


def _as_strings(value, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise RegistryError(f"{where}: ожидался список строк")


def _parse_param(raw, where: str) -> Optional[Param]:
    """Парсинг необязательного поля param из YAML."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: param должен быть словарём")
    name = raw.get("name")
    pattern = raw.get("pattern")
    if not name or not isinstance(name, str):
        raise RegistryError(f"{where}: param.name обязателен и должен быть строкой")
    if not pattern or not isinstance(pattern, str):
        raise RegistryError(f"{where}: param.pattern обязателен и должен быть строкой")
    try:
        re.compile(pattern)
    except re.error as e:
        raise RegistryError(f"{where}: param.pattern невалидный regex: {e}")
    req = raw.get("required", "true")
    if isinstance(req, bool):
        req = "true" if req else "false"
    if req not in ("true", "false", "ask"):
        raise RegistryError(
            f"{where}: param.required должен быть true/false/ask, получено {req!r}"
        )
    resolve = raw.get("resolve")
    if resolve is not None:
        resolve = str(resolve)
        if resolve not in PARAM_RESOLVES:
            raise RegistryError(
                f"{where}: param.resolve должен быть одним из "
                f"{PARAM_RESOLVES}, получено {resolve!r}"
            )
    return Param(name=name, pattern=pattern, required=req, resolve=resolve)


def declaration_from_dict(raw: dict) -> Declaration:
    """Строит Declaration из словаря YAML, проверяя обязательные поля."""
    if not isinstance(raw, dict):
        raise RegistryError(
            f"декларация должна быть словарём, получено {type(raw).__name__}"
        )
    decl_id = raw.get("id")
    if not decl_id or not isinstance(decl_id, str):
        raise RegistryError(f"декларация без обязательного непустого 'id': {raw!r}")
    where = f"декларация '{decl_id}'"
    for field in REQUIRED_FIELDS:
        if raw.get(field) is None:
            raise RegistryError(f"{where}: отсутствует обязательное поле '{field}'")
    return Declaration(
        id=decl_id,
        desc=str(raw["desc"]),
        executor=str(raw["executor"]),
        reversible=bool(raw["reversible"]),
        confirm=bool(raw["confirm"]),
        triggers=_as_strings(raw["triggers"], where),
        followup=str(raw["followup"]),
        legacy=_as_strings(raw.get("legacy"), where),
        context=raw.get("context"),
        param=_parse_param(raw.get("param"), where),
    )


def unreachable(declarations: Iterable[Declaration]) -> set[str]:
    """id деклараций, для которых нет зарегистрированного хендлера.

    Импорт executor локальный: sakura_core/executor.py импортирует реестр,
    обратный импорт на уровне модуля дал бы цикл.

    Пустая таблица также означает отсутствие исполнения: стартовая проверка
    должна отклонять незагруженные домены, а не пропускать их молча.
    """
    from sakura_core.executor import get_handler

    return {d.id for d in declarations if get_handler(d.id) is None}


def validate(declarations: Iterable[Declaration], *,
             require_handlers: bool = False) -> None:
    """Валидация реестра. Бросает RegistryError, если контракт нарушен.

    Смысл реестра в том, что двадцатое действие нельзя добавить, тихо
    сломав девятнадцатое. Это обеспечивает валидация.

    require_handlers=True (ставит load(), то есть старт бота) добавляет
    проверку достижимости: декларация без хендлера — ошибка на старте, а не
    молчаливое «не исполнено» в бою. Проверка не для произвольных списков
    деклараций (синтетические Declaration в тестах хендлеров не имеют),
    поэтому по умолчанию выключена.
    """
    declarations = list(declarations)
    seen_ids: set[str] = set()
    by_trigger: dict[str, list[Declaration]] = {}

    for d in declarations:
        if d.id in seen_ids:
            raise RegistryError(f"два действия с одинаковым id: '{d.id}'")
        seen_ids.add(d.id)

        if not d.triggers:
            raise RegistryError(f"'{d.id}': triggers пустой")

        if d.executor not in EXECUTORS:
            raise RegistryError(
                f"'{d.id}': неизвестный executor '{d.executor}' "
                f"(допустимо: {', '.join(EXECUTORS)})"
            )

        if d.context is not None and d.context not in CONTEXTS:
            raise RegistryError(
                f"'{d.id}': недопустимый context '{d.context}' "
                f"(допустимо: {', '.join(CONTEXTS)})"
            )

        if d.followup not in FOLLOWUPS:
            raise RegistryError(
                f"'{d.id}': недопустимый followup '{d.followup}' "
                f"(допустимо: {', '.join(FOLLOWUPS)})"
            )

        for trigger in d.triggers:
            by_trigger.setdefault(trigger, []).append(d)

    for trigger, owners in by_trigger.items():
        if len(owners) <= 1:
            continue
        # Проверяем неоднозначность: владельцы с context=None
        no_ctx = [o for o in owners if o.context is None]
        if len(no_ctx) < 2:
            continue
        # Среди no_ctx: если НИ У ОДНОГО нет param — это неразрешимая ничья.
        # Если хотя бы у одного есть param — tie-breaking на runtime решит.
        no_param = [o for o in no_ctx if o.param is None]
        if len(no_param) == len(no_ctx):
            names = ", ".join(f"'{o.id}'" for o in owners)
            raise RegistryError(
                f"триггер '{trigger}' принадлежит нескольким действиям "
                f"без context и без param: {names} — неразрешимая неоднозначность"
            )

    if require_handlers:
        gaps = unreachable(declarations) - KNOWN_UNREACHABLE
        if gaps:
            raise RegistryError(
                "декларация без хендлера (исполнять нечем): "
                f"{', '.join(sorted(gaps))} — подключи таблицу домена в "
                "bridge._load_capabilities() либо внеси id в KNOWN_UNREACHABLE"
            )


def load(path: Path = REGISTRY_PATH) -> list[Declaration]:
    """Читает YAML и отдаёт список деклараций. Падает на старте, а не в бою.

    require_handlers=True: декларация без хендлера — отказ на старте. Это
    тот же класс дыры, что нашёлся на этапе 6 (13 id, включая coding.*,
    files.open, calendar.list, попадали в каталог LLM, но исполнения не
    имели — ни в реестре, ни у агента), только теперь она видна сразу,
    а не в отчёте после разбора.
    """
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, list):
        raise RegistryError(f"{path}: ожидался YAML-список деклараций")
    declarations = [declaration_from_dict(item) for item in raw]
    validate(declarations, require_handlers=True)
    log.info("[registry] загружено деклараций: %d", len(declarations))
    return declarations


# ── установленные приложения (для param.resolve: installed_apps) ─────────
# Агент присылает список при каждой регистрации (apps_list после register).
# Сервер держит его в памяти: рестарт сервера → агент переподключится и
# пришлёт заново. None — списка ещё нет (агент не подключён): триггеры с
# resolve не матчатся вовсе, фраза уходит дальше по роутеру (LLM), как до
# появления app.switch.
_installed_apps: Optional[frozenset[str]] = None


def set_installed_apps(apps, extra: Optional[Iterable[str]] = None) -> None:
    """Сохранить имена установленных приложений (сравнение без учёта регистра).

    apps — словарь «имя → путь/протокол» от агента или итератор имён;
    None — списка нет (агент не подключён). extra — дополнительные
    разговорные имена (keys из memory/apps_mapping_<device>.json, их
    строит sakura_core.apps.analyze_apps: «дискорд» → Discord.exe).
    """
    global _installed_apps
    if apps is None and not extra:
        _installed_apps = None
        return
    names: set[str] = set()
    if isinstance(apps, dict):
        names.update(str(k) for k in apps)
    elif apps:
        names.update(str(k) for k in apps)
    if extra:
        names.update(str(k) for k in extra)
    _installed_apps = frozenset(
        n.strip().lower() for n in names if n and n.strip()
    )
    log.info("[registry] список приложений: %d", len(_installed_apps))


def installed_apps() -> Optional[frozenset[str]]:
    """Текущий список установленных приложений (нижний регистр) или None."""
    return _installed_apps


def resolve_passes(value: Optional[str]) -> bool:
    """Значение параметра — установленное приложение? (проверка resolve)."""
    apps = _installed_apps
    if not apps or not value:
        return False
    return value.strip().lower() in apps


class TriggerIndex:
    """Индекс триггеров: поиск от самых длинных к коротким, по границам слов."""

    def __init__(self, declarations: Iterable[Declaration]):
        entries: list[tuple[str, Declaration]] = []
        for d in declarations:
            for trigger in d.triggers:
                entries.append((trigger, d))
        entries.sort(key=lambda item: len(item[0]), reverse=True)
        self._entries = [
            (trigger, re.compile(rf"(?<!\w){re.escape(trigger)}(?!\w)", re.IGNORECASE), d)
            for trigger, d in entries
        ]

    def match(
        self, text: str, context: Optional[str] = None
    ) -> Optional[tuple[str, Declaration, Optional[str], bool]]:
        """Самый длинный совпавший триггер во фразе.

        context — текущий контекст ('playing:music', 'window:youtube',
        'window:browser') или None. Декларации с context участвуют только
        при совпадении контекста; без context — при любом.

        При равной длине триггера выигрывает декларация, у которой
        param.extract() вернул значение.

        param.required:
          "true"  — нет значения → декларация пропускается
          "false" — отсутствие нормально
          "ask"   — нет значения → нужен clarify, декларация возвращается
                    с needs_clarify=True

        param.resolve ("installed_apps"):
          значения параметра должно оказаться в списке установленных
          приложений (set_installed_apps), иначе декларация пропускается —
          как при required: true. Списка нет (агент не подключён, пустой
          список) — триггер с resolve не матчится вовсе.

        Возвращает (триггер, декларация, param_value, needs_clarify) либо None.
        """
        if not text:
            return None
        lowered = text.lower()

        best_len = 0
        best_matches: list[tuple[str, Declaration, Optional[str], bool]] = []

        for trigger, pattern, declaration in self._entries:
            trigger_len = len(trigger)

            if best_len > 0 and trigger_len < best_len:
                break

            if declaration.context is not None and declaration.context != context:
                continue

            if not pattern.search(lowered):
                continue

            param_value = None
            needs_clarify = False
            resolve = declaration.param.resolve if declaration.param else None
            apps = installed_apps() if resolve else None
            if resolve and not apps:
                continue  # списка нет (агент не подключён) — resolve-триггер молчит
            if declaration.param is not None:
                param_value = declaration.param.extract(text)
                req = declaration.param.required
                if req == "true" and param_value is None:
                    continue  # required — пропускаем
                if req == "ask" and param_value is None:
                    needs_clarify = True  # помечаем, что нужен clarify
                if resolve and param_value is not None \
                        and param_value.strip().lower() not in apps:
                    continue  # параметр — не установленное приложение, пропускаем

            if trigger_len > best_len:
                best_len = trigger_len
                best_matches = [(trigger, declaration, param_value, needs_clarify)]
            elif trigger_len == best_len:
                best_matches.append((trigger, declaration, param_value, needs_clarify))

        if not best_matches:
            return None

        # Среди совпадений максимальной длины предпочесть то, где param извлечён
        for match in best_matches:
            if match[2] is not None:
                return match
        # Если ни у одного param не извлечён — вернуть первый (с needs_clarify если есть)
        return best_matches[0]


def build_index(declarations: Iterable[Declaration]) -> TriggerIndex:
    """Строит индекс триггеров по списку деклараций."""
    return TriggerIndex(declarations)


def build_llm_catalog(declarations: Iterable[Declaration]) -> str:
    """Каталог для LLM из id + desc всех деклараций (замена INTENTS_PROMPT).

    Триггеры и каталог — одни и те же данные, поэтому действие, забытое
    в каталоге (находка 2 инвентаризации), невозможно по построению.
    """
    return "\n".join(f"- {d.id}: {d.desc}" for d in declarations)


# ── followup по имени на проводе ────────────────────────────────────────
# Агент отвечает именами действий (music_info, music_next, ext:page_content),
# а не каноническими id. Поэтому индекс строится по обоим написаниям:
# канонический id и legacy-имя. Знание о том, зазвучит ли модель после
# исполнения, живёт в реестре — мост и command_result читают его здесь.

_followup_index: Optional[dict[str, str]] = None


def _build_followup_index(declarations: Iterable[Declaration]) -> dict[str, str]:
    index: dict[str, str] = {}
    for d in declarations:
        index[d.id] = d.followup
        for name in d.legacy:
            index[name] = d.followup
    return index


def followup_index(declarations: Optional[Iterable[Declaration]] = None) -> dict[str, str]:
    """Индекс «имя на проводе → followup». Без аргумента — по реестру из YAML."""
    global _followup_index
    if declarations is not None:
        return _build_followup_index(declarations)
    if _followup_index is None:
        _followup_index = _build_followup_index(load())
    return _followup_index


def followup_for(action: str, declarations: Optional[Iterable[Declaration]] = None) -> str:
    """followup действия по имени на проводе (канонический id или legacy).

    Неизвестное имя считается ack: путь, который не смог опознать действие,
    не должен молчать — «Готово» безопаснее тишины.
    """
    if not action:
        return "ack"
    return followup_index(declarations).get(action, "ack")

