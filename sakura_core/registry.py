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
REQUIRED_FIELDS = ("id", "desc", "executor", "reversible", "confirm", "triggers")


class RegistryError(Exception):
    """Нарушение контракта реестра. Падать на старте, а не в бою."""


@dataclass(frozen=True)
class Param:
    """Параметр, извлекаемый из текста пользователя.

    pattern - regex с одной группой захвата.
    Извлекает значение из полного текста фразы пользователя.
    """

    name: str
    pattern: str
    required: bool = True

    def extract(self, text: str) -> Optional[str]:
        """Извлечь значение параметра из текста. None если не найдено."""
        m = re.search(self.pattern, text, re.IGNORECASE)
        if not m:
            return None
        # Используем первую непустую группу захвата
        for g in m.groups():
            if g is not None:
                return g
        return None


@dataclass(frozen=True)
class Declaration:
    """Одна способность: канонический id, описание, исполнитель, триггеры."""

    id: str
    desc: str
    executor: str
    reversible: bool
    confirm: bool
    triggers: tuple[str, ...]
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
    return Param(name=name, pattern=pattern, required=bool(raw.get("required", True)))


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
        legacy=_as_strings(raw.get("legacy"), where),
        context=raw.get("context"),
        param=_parse_param(raw.get("param"), where),
    )


def validate(declarations: Iterable[Declaration]) -> None:
    """Валидация реестра. Бросает RegistryError, если контракт нарушен.

    Смысл реестра в том, что двадцатое действие нельзя добавить, тихо
    сломав девятнадцатое. Это обеспечивает валидация.
    """
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

        for trigger in d.triggers:
            by_trigger.setdefault(trigger, []).append(d)

    for trigger, owners in by_trigger.items():
        if len(owners) > 1 and any(o.context is None for o in owners):
            names = ", ".join(f"'{o.id}'" for o in owners)
            raise RegistryError(
                f"триггер '{trigger}' принадлежит нескольким действиям, "
                f"и хотя бы у одного нет context: {names}"
            )


def load(path: Path = REGISTRY_PATH) -> list[Declaration]:
    """Читает YAML и отдаёт список деклараций. Падает на старте, а не в бою."""
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, list):
        raise RegistryError(f"{path}: ожидался YAML-список деклараций")
    declarations = [declaration_from_dict(item) for item in raw]
    validate(declarations)
    log.info("[registry] загружено деклараций: %d", len(declarations))
    return declarations


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
    ) -> Optional[tuple[str, Declaration, Optional[str]]]:
        """Самый длинный совпавший триггер во фразе.

        context — текущий контекст ('playing:music', 'window:youtube',
        'window:browser') или None. Декларации с context участвуют только
        при совпадении контекста; без context — при любом.

        Возвращает (триггер, декларация, param_value) либо None.
        param_value — значение параметра, извлечённое из текста (или None).
        """
        if not text:
            return None
        lowered = text.lower()
        for trigger, pattern, declaration in self._entries:
            if declaration.context is not None and declaration.context != context:
                continue
            if pattern.search(lowered):
                param_value = None
                if declaration.param is not None:
                    param_value = declaration.param.extract(text)
                return trigger, declaration, param_value
        return None


def build_index(declarations: Iterable[Declaration]) -> TriggerIndex:
    """Строит индекс триггеров по списку деклараций."""
    return TriggerIndex(declarations)


def build_llm_catalog(declarations: Iterable[Declaration]) -> str:
    """Каталог для LLM из id + desc всех деклараций (замена INTENTS_PROMPT).

    Триггеры и каталог — одни и те же данные, поэтому действие, забытое
    в каталоге (находка 2 инвентаризации), невозможно по построению.
    """
    return "\n".join(f"- {d.id}: {d.desc}" for d in declarations)

