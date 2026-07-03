"""
modules/voice_router.py — Умный маршрутизатор голосовых команд.

Возможности:
  - Стемминг (сравнение по корню слова)
  - Fuzzy matching (нечёткое сравнение)
  - Приоритеты модулей
  - Контекст (последний использованный модуль)
  - Авто-обнаружение модулей с handle_voice
  - Логирование и аналитика
"""

import logging
import os
import re
import time
from typing import Optional, Callable
from difflib import SequenceMatcher

log = logging.getLogger("sakura.voice_router")

# ── Стемминг для русского языка ──────────────────────────────────────

# Суффиксы для удаления (порядок важен — от длинных к коротким)
_SUFFIXES = [
    "аний", "ания", "ание", "анием", "ании",
    "ений", "ения", "ение", "ением", "ении",
    "ний", "ния", "ние", "нием", "нии",
    "ть", "ти", "тей", "тая", "тое", "тые",
    "ый", "ая", "ое", "ые", "ий", "ая", "ое", "ие",
    "ов", "ев", "ам", "ям", "ом", "ем",
    "ы", "и", "а", "е", "о", "у", "ю",
]

# Исключения — слова которые не стоит стемминговать
_STEM_exceptions = {
    "да": "да",
    "нет": "нет",
    "ок": "ок",
    "привет": "привет",
    "пока": "пока",
}


def stem(word: str) -> str:
    """
    Возвращает корень слова (стемминг для русского).
    Пример: "предсказаний" → "предсказан"
    """
    word = word.lower().strip()

    if word in _STEM_exceptions:
        return _STEM_exceptions[word]

    # Убираем суффиксы
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]

    return word


def stem_match(text: str, trigger: str) -> bool:
    """
    Сравнивает текст и триггер по корням слов.
    "предсказаний" matches "предсказание" → True
    """
    text_stems = [stem(w) for w in text.lower().split()]
    trigger_stem = stem(trigger.lower())

    return any(trigger_stem in ts or ts in trigger_stem for ts in text_stems)


# ── Fuzzy matching ──────────────────────────────────────────────────

def fuzzy_score(text: str, trigger: str) -> float:
    """
    Возвращает оценку схожести 0.0 - 1.0.
    Учитывает частичное совпадение.
    """
    text_lower = text.lower()
    trigger_lower = trigger.lower()

    # Точное совпадение
    if trigger_lower in text_lower:
        return 1.0

    # По корням
    if stem_match(text_lower, trigger_lower):
        return 0.9

    # Последовательное совпадение
    words = text_lower.split()
    for word in words:
        ratio = SequenceMatcher(None, word, trigger_lower).ratio()
        if ratio > 0.7:
            return ratio * 0.8

    # Общее совпадение
    return SequenceMatcher(None, text_lower, trigger_lower).ratio() * 0.5


# ── Регистр модулей ─────────────────────────────────────────────────

class VoiceModule:
    """Метаданные голосового модуля."""

    def __init__(self, name: str, triggers: list[str],
                 handler: Callable, priority: int = 0,
                 description: str = ""):
        self.name = name
        self.triggers = triggers
        self.handler = handler
        self.priority = priority
        self.description = description
        self.hits = 0
        self.last_used = 0.0

    def match(self, text: str) -> float:
        """Возвращает лучший score совпадения."""
        best = 0.0
        for trigger in self.triggers:
            score = fuzzy_score(text, trigger)
            if score > best:
                best = score
        return best


# ── Глобальный роутер ───────────────────────────────────────────────

class VoiceRouter:
    """Центральный маршрутизатор голосовых команд."""

    def __init__(self):
        self._modules: dict[str, VoiceModule] = {}
        self._last_module: Optional[str] = None
        self._last_command_time: float = 0.0
        self._context_timeout = 30.0  # секунд — контекст живёт

    def register(self, name: str, triggers: list[str],
                 handler: Callable, priority: int = 0,
                 description: str = ""):
        """Регистрирует модуль."""
        self._modules[name] = VoiceModule(
            name=name, triggers=triggers,
            handler=handler, priority=priority,
            description=description
        )
        log.debug(f"[router] Зарегистрирован: {name} ({len(triggers)} триггеров)")

    def auto_discover(self):
        """Авто-обнаруживает модули с VOICE_TRIGGERS + handle_voice."""
        import glob
        import importlib

        mod_files = glob.glob("/opt/sakura/modules/*.py")
        skip = {"voice_router", "coding", "prompt_builder", "memory_validator"}

        for mod_path in mod_files:
            mod_name = os.path.basename(mod_path).replace(".py", "")
            if mod_name.startswith("_") or mod_name in skip:
                continue

            try:
                mod = importlib.import_module(f"modules.{mod_name}")
                if hasattr(mod, "VOICE_TRIGGERS") and hasattr(mod, "handle_voice"):
                    triggers = getattr(mod, "VOICE_TRIGGERS", [])
                    handler = getattr(mod, "handle_voice")
                    priority = getattr(mod, "VOICE_PRIORITY", 0)
                    desc = getattr(mod, "__doc__", "") or mod_name

                    if triggers and callable(handler):
                        self.register(mod_name, triggers, handler,
                                     priority, desc[:100])
            except Exception as e:
                log.debug(f"[router] Ошибка загрузки {mod_name}: {e}")

        log.info(f"[router] Загружено модулей: {len(self._modules)}")

    def route(self, text: str) -> Optional[str]:
        """
        Находит лучший модуль для команды.
        Возвращает ответ или None.
        """
        text_lower = text.lower().strip()
        if not text_lower:
            return None

        # Проверяем контекст (повторное обращение к тому же модулю)
        if self._last_module and (time.monotonic() - self._last_command_time) < self._context_timeout:
            if self._last_module in self._modules:
                mod = self._modules[self._last_module]
                result = mod.handler(text)
                if result:
                    mod.hits += 1
                    mod.last_used = time.monotonic()
                    log.info(f"[router] Контекст: {self._last_module}")
                    return result

        # Ищем лучший модуль
        candidates = []
        for name, mod in self._modules.items():
            score = mod.match(text_lower)
            if score > 0.5:  # Порог совпадения
                candidates.append((score, mod))

        if not candidates:
            return None

        # Сортируем по score и приоритету
        candidates.sort(key=lambda x: (x[0], x[1].priority), reverse=True)

        best_score, best_mod = candidates[0]

        # Вызываем обработчик
        result = best_mod.handler(text)
        if result:
            best_mod.hits += 1
            best_mod.last_used = time.monotonic()
            self._last_module = best_mod.name
            self._last_command_time = time.monotonic()
            log.info(f"[router] {best_mod.name}: score={best_score:.2f}")
            return result

        return None

    def get_stats(self) -> dict:
        """Статистика использования."""
        return {
            name: {"hits": mod.hits, "last_used": mod.last_used}
            for name, mod in self._modules.items()
            if mod.hits > 0
        }

    def list_modules(self) -> list[dict]:
        """Список зарегистрированных модулей."""
        return [
            {"name": mod.name, "triggers": mod.triggers,
             "priority": mod.priority, "hits": mod.hits}
            for mod in self._modules.values()
        ]


# ── Глобальный экземпляр ────────────────────────────────────────────

_router: Optional[VoiceRouter] = None


def get_router() -> VoiceRouter:
    """Возвращает глобальный роутер (создаёт при первом вызове)."""
    global _router
    if _router is None:
        _router = VoiceRouter()
        _router.auto_discover()
    return _router


def handle_voice(text: str) -> Optional[str]:
    """
    Главная функция — обрабатывает голосовую команду.
    Вызывать из main.py в voice_command handler.
    """
    router = get_router()
    return router.route(text)
