"""
modules/intent_classifier.py — Семантический классификатор намерений.

Определяет тип входящего сообщения:
  - command: команда (императив) — "включи музыку", "открой браузер"
  - request: запрос — "что думаешь", "расскажи про"
  - conversation: разговор — "привет", "как дела"

Не привязан к конкретным словам — использует LLM для понимания смысла.
"""

import asyncio
import json
import logging
import re
from typing import Optional
from dataclasses import dataclass

from config import get_active_key, mark_key_used

log = logging.getLogger("sakura.intent")

INTENT_PROMPT = """
Ты — классификатор намерений голосового ассистента Сакура.

Определи тип сообщения пользователя и верни ТОЛЬКО JSON.

ТИПЫ:
1. "command" — команда/императив. Пользователь хочет чтобы что-то БЫЛО СДЕЛАНО:
   - открыть/закрыть приложение
   - включить/выключить музыку
   - сделать скриншот
   - изменить громкость
   - отправить сообщение
   - любое действие над системой/устройством
   
2. "request" — запрос. Пользователь хочет ПОЛУЧИТЬ ИНФОРМАЦИЮ:
   - вопрос ("что думаешь", "сколько времени")
   - просьба рассказать/объяснить
   - запрос на поиск информации
   - просьба описать/показать
   
3. "conversation" — разговор. Общение без явной цели:
   - приветствие
   - реакция на ответ
   - шутка/комплимент
   - эмоциональное высказывание

ПРАВИЛА:
- Если есть хотя бы один глагол действия (включи, открой, закрой, сделай, отправь, поставь) → command
- Если есть вопросительное слово (что, как, почему, когда, где, кто) без глагола действия → request
- Если это приветствие, комплимент или эмоция → conversation
- Неоднозначно без контекста → conversation

Примеры:
"включи музыку" → {"type": "command", "intent": "music_play", "confidence": 0.95}
"что думаешь про это" → {"type": "request", "intent": "opinion", "confidence": 0.9}
"привет как дела" → {"type": "conversation", "intent": "greeting", "confidence": 0.95}
"открой стим" → {"type": "command", "intent": "open_app", "confidence": 0.95}
"сколько времени" → {"type": "request", "intent": "time_query", "confidence": 0.9}
"молодец" → {"type": "conversation", "intent": "praise", "confidence": 0.9}
"скажи что на экране" → {"type": "command", "intent": "screenshot_describe", "confidence": 0.85}
"какая погода" → {"type": "request", "intent": "weather_query", "confidence": 0.9}
"отправь в тг" → {"type": "command", "intent": "send_tg", "confidence": 0.9}

Верни JSON:
{"type": "command|request|conversation", "intent": "строка", "confidence": 0.0-1.0}
"""


@dataclass
class IntentResult:
    """Результат классификации намерения."""
    type: str  # "command" | "request" | "conversation"
    intent: str  # конкретное намерение
    confidence: float  # 0.0 - 1.0


def _fast_classify(text: str) -> Optional[IntentResult]:
    """
    Быстрая классификация без LLM — по паттернам.
    Возвращает None если не уверены.
    """
    tl = text.lower().strip().rstrip(".?!")

    # Явные командные маркеры
    _command_markers = (
        "включи", "выключи", "открой", "закрой", "сделай", "поставь",
        "найди", "отправь", "скинь", "напиши", "покажи", "запусти",
        "останови", "прибавь", "убавь", "громче", "тише", "скриншот",
        "врубай", "вырубай", "переключи", "дублируй", "обнови",
    )
    if any(m in tl for m in _command_markers):
        return IntentResult(type="command", intent="fast_detect", confidence=0.85)

    # Явные разговорные маркеры
    _conversation_markers = (
        "привет", "пока", "ок", "ага", "нет", "да", "молодец",
        "спасибо", "хорошо", "плохо", "круто", "супер", "класс",
    )
    if tl in _conversation_markers or any(tl.startswith(m) for m in _conversation_markers):
        return IntentResult(type="conversation", intent="fast_detect", confidence=0.8)

    # Вопросы — запросы
    _question_markers = (
        "что", "как", "почему", "зачем", "когда", "где", "кто",
        "сколько", "который", "можно ли", "стоит ли",
    )
    if tl.endswith("?") or any(tl.startswith(m) for m in _question_markers):
        # Но если есть глагол действия — это команда
        _action_verbs = ("включи", "открой", "закрой", "сделай", "поставь", "найди")
        if not any(v in tl for v in _action_verbs):
            return IntentResult(type="request", intent="fast_detect", confidence=0.75)

    return None


async def classify_intent(text: str) -> IntentResult:
    """
    Классифицирует намерение пользователя.
    
    1. Быстрый паттерн (без LLM)
    2. LLM-классификация (если быстрый не сработал)
    
    Возвращает IntentResult с типом, намерением и уверенностью.
    """
    # Уровень 1: быстрая классификация
    fast = _fast_classify(text)
    if fast and fast.confidence >= 0.85:
        log.info(f"[intent] {text!r} → {fast.type} (fast, {fast.confidence:.2f})")
        return fast

    # Уровень 2: LLM-классификация
    key = get_active_key()
    if not key:
        # Fallback: если нет ключа — считаем разговором
        return IntentResult(type="conversation", intent="no_key", confidence=0.5)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        prompt = f'Пользователь сказал: "{text}"\n\nТип:'

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.1-flash-lite",
            contents=[types.Content(
                role="user",
                parts=[types.Part(text=prompt)]
            )],
            config=types.GenerateContentConfig(
                system_instruction=INTENT_PROMPT,
                temperature=0.0,
                max_output_tokens=100,
            )
        )
        mark_key_used(key)

        raw = (response.text or "").strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)

        intent_type = result.get("type", "conversation")
        intent = result.get("intent", "unknown")
        confidence = float(result.get("confidence", 0.5))

        # Валидация
        if intent_type not in ("command", "request", "conversation"):
            intent_type = "conversation"

        log.info(f"[intent] {text!r} → {intent_type}/{intent} ({confidence:.2f})")
        return IntentResult(type=intent_type, intent=intent, confidence=confidence)

    except json.JSONDecodeError:
        log.debug(f"[intent] JSON error: {raw!r}")
        return IntentResult(type="conversation", intent="parse_error", confidence=0.3)
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower():
            log.warning("[intent] Rate limited")
            return IntentResult(type="conversation", intent="rate_limited", confidence=0.3)
        log.debug(f"[intent] error: {e}")
        return IntentResult(type="conversation", intent="error", confidence=0.3)


def is_command(text: str) -> bool:
    """
    Быстрая проверка: является ли текст командой.
    Используется для раннего фильтра before LLM routing.
    """
    tl = text.lower().strip().rstrip(".?!")

    # Хардкод — без LLM
    _command_verbs = (
        "включи", "выключи", "открой", "закрой", "сделай", "поставь",
        "найди", "отправь", "скинь", "напиши", "покажи", "запусти",
        "останови", "прибавь", "убавь", "громче", "тише", "врубай",
        "вырубай", "переключи", "дублируй", "обнови", "прокрути",
        "заблокируй", "выключи комп", "перезагрузи",
    )
    return any(v in tl for v in _command_verbs)


def is_question(text: str) -> bool:
    """
    Быстрая проверка: является ли текст вопросом/запросом.
    """
    tl = text.lower().strip()
    return tl.endswith("?") or any(tl.startswith(w) for w in (
        "что", "как", "почему", "зачем", "когда", "где", "кто",
        "сколько", "который", "а ты", "ты помнишь", "расскажи",
    ))
