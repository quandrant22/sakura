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

ДЛИНА ОТВЕТА:
Определи также, насколько развёрнутым должен быть ответ:
"length": "short" — ПО УМОЛЧАНИЮ: разговор, реакция, жалоба, рассказ о себе, эмоция, приветствие, короткий вопрос. Почти всё — short. 1-2 предложения.
"length": "medium" — ТОЛЬКО когда Мастер явно просит оценку/мнение или обсуждение темы ("как думаешь", "что скажешь про", "оцени"). 2-3 предложения.
"length": "long" — ТОЛЬКО явная просьба развернуть ("расскажи", "объясни", "опиши", "подробно", "в деталях"). Сколько нужно.
Если сомневаешься между short и medium — выбирай short.

ПРАВИЛА:
- Если есть хотя бы один глагол действия (включи, открой, закрой, сделай, отправь, поставь) → command
- Если есть вопросительное слово (что, как, почему, когда, где, кто) без глагола действия → request
- Если это приветствие, комплимент или эмоция → conversation
- Неоднозначно без контекста → conversation

Примеры:
"включи музыку" → {"type": "command", "intent": "music_play", "confidence": 0.95, "length": "short"}
"привет как дела" → {"type": "conversation", "intent": "greeting", "confidence": 0.95, "length": "short"}
"мне ничего не помогает, мучаюсь" → {"type": "conversation", "intent": "complaint", "confidence": 0.85, "length": "short"}
"я плохо сплю в последнее время" → {"type": "conversation", "intent": "self_report", "confidence": 0.85, "length": "short"}
"вот занимаюсь кодом, слушаю музыку" → {"type": "conversation", "intent": "sharing", "confidence": 0.85, "length": "short"}
"как думаешь, стоит ли брать эту игру" → {"type": "request", "intent": "opinion", "confidence": 0.9, "length": "medium"}
"что думаешь про киберпанк" → {"type": "request", "intent": "opinion", "confidence": 0.9, "length": "medium"}
"расскажи про историю Японии" → {"type": "request", "intent": "tell_about", "confidence": 0.9, "length": "long"}
"объясни как работает двигатель" → {"type": "request", "intent": "explain", "confidence": 0.9, "length": "long"}
"сколько времени" → {"type": "request", "intent": "time_query", "confidence": 0.9, "length": "short"}
"молодец" → {"type": "conversation", "intent": "praise", "confidence": 0.9, "length": "short"}

Верни JSON:
{"type": "command|request|conversation", "intent": "строка", "confidence": 0.0-1.0, "length": "short|medium|long"}
"""


@dataclass
class IntentResult:
    """Результат классификации намерения."""
    type: str  # "command" | "request" | "conversation"
    intent: str  # конкретное намерение
    confidence: float  # 0.0 - 1.0
    length: str = "short"  # "short" | "medium" | "long"


def _fast_classify(text: str) -> Optional[IntentResult]:
    """
    Быстрая классификация без LLM — по паттернам.
    Возвращает None если не уверены.
    """
    tl = text.lower().strip().rstrip(".?!")

    # Явные маркеры длинного ответа — сразу request + long
    _long_markers = (
        "расскажи", "объясни", "подробно", "в деталях", "опиши",
        "рассказать", "объяснить", "описать", "разверни",
    )
    if any(m in tl for m in _long_markers):
        return IntentResult(type="request", intent="fast_detect", confidence=0.8, length="long")

    # Явные командные маркеры
    _command_markers = (
        "включи", "выключи", "открой", "закрой", "сделай", "поставь",
        "найди", "отправь", "скинь", "напиши", "покажи", "запусти",
        "останови", "прибавь", "убавь", "громче", "тише", "скриншот",
        "врубай", "вырубай", "переключи", "дублируй", "обнови",
    )
    if any(m in tl for m in _command_markers):
        return IntentResult(type="command", intent="fast_detect", confidence=0.85, length="short")

    # Явные разговорные маркеры
    _conversation_markers = (
        "привет", "пока", "ок", "ага", "нет", "да", "молодец",
        "спасибо", "хорошо", "плохо", "круто", "супер", "класс",
    )
    if tl in _conversation_markers or any(tl.startswith(m) for m in _conversation_markers):
        return IntentResult(type="conversation", intent="fast_detect", confidence=0.8, length="short")

    # Вопросы — запросы
    _question_markers = (
        "что", "как", "почему", "зачем", "когда", "где", "кто",
        "сколько", "который", "можно ли", "стоит ли",
    )
    if tl.endswith("?") or any(tl.startswith(m) for m in _question_markers):
        # Но если есть глагол действия — это команда
        _action_verbs = ("включи", "открой", "закрой", "сделай", "поставь", "найди")
        if not any(v in tl for v in _action_verbs):
            # Средняя длина для вопросов мнения/обсуждения
            _medium_markers = ("что думаешь", "как считаешь", "как насчёт", "что скажешь")
            mid = "medium" if any(m in tl for m in _medium_markers) else "short"
            return IntentResult(type="request", intent="fast_detect", confidence=0.75, length=mid)

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
        log.info(f"[intent] {text!r} → {fast.type}/{fast.intent}/len={fast.length} (fast, {fast.confidence:.2f})")
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
        length = result.get("length", "short")

        # Валидация
        if intent_type not in ("command", "request", "conversation"):
            intent_type = "conversation"
        if length not in ("short", "medium", "long"):
            length = "short"

        log.info(f"[intent] {text!r} → {intent_type}/{intent}/len={length} ({confidence:.2f})")
        return IntentResult(type=intent_type, intent=intent, confidence=confidence, length=length)

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
