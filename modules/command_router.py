"""
modules/command_router.py — LLM-роутер команд на основе намерений.

Вместо списка примеров — описания намерений. LLM сам понимает
что имел в виду пользователь без явного перечисления каждой фразы.

Критические команды (питание ПК, чайник) — точный матчинг, без LLM.
"""

import asyncio
import json
import logging
import re

from config import get_active_key, mark_key_used, mark_key_rate_limited

log = logging.getLogger("sakura.router")

# ── Описания намерений ────────────────────────────────────────────────

INTENTS_PROMPT = """
Ты — роутер команд голосового ассистента Сакура (Windows ПК).
Получаешь текст пользователя и возвращаешь ТОЛЬКО JSON. Никакого текста кроме JSON.

Сакура управляет компьютером пользователя — может открывать приложения, управлять музыкой,
браузером, громкостью и т.д. Определи намерение и верни подходящее действие.
Если это вопрос или разговор — верни {"action": null}.

НАМЕРЕНИЯ И ДЕЙСТВИЯ:

МУЗЫКА (Яндекс Музыка):
- Запустить/включить/поставить/врубить музыку — любая просьба начать воспроизведение музыки → {"action": "open_app", "arg": "яндекс музыка"}
- Пауза, стоп, продолжить воспроизведение → {"action": "music_play_pause"}
- Следующий трек/песня → {"action": "music_next"}
- Предыдущий трек/песня → {"action": "music_prev"}
- Лайкнуть трек (не видео) → {"action": "music_like"}
- Дизлайкнуть трек → {"action": "music_dislike"}
- Что играет, текущий трек → {"action": "music_info"}
- Перемешать, случайный порядок → {"action": "music:shuffle"}
- Повтор трека → {"action": "music:repeat"}
- Моя волна → {"action": "music_play_wave"}
- Включить/поставь/найди конкретный трек или исполнителя → {"action": "music_play_track:ЗАПРОС"}
- Включить плейлист → {"action": "music_play_playlist:НАЗВАНИЕ"}
- История, плейлисты, любимые → {"action": "music_history"} / {"action": "music_playlists"} / {"action": "music_liked_tracks"}
- Поиск треков (без воспроизведения) → {"action": "music_search:ЗАПРОС"}

YOUTUBE:
- Пауза/стоп/воспроизведение на YouTube → {"action": "youtube_pause", "agent": true}
- Следующее видео на YouTube → {"action": "youtube_next", "agent": true}
- Перемотать вперёд → {"action": "youtube_forward", "agent": true}
- Перемотать назад → {"action": "youtube_rewind", "agent": true}
- Полный экран → {"action": "youtube_fullscreen", "agent": true}
- Театральный режим → {"action": "youtube_theater", "agent": true}
- Мини-плеер → {"action": "youtube_mini", "agent": true}
- Субтитры → {"action": "youtube_sub_toggle", "agent": true}
- Скорость воспроизведения быстрее → {"action": "youtube_speed_up", "agent": true}
- Скорость воспроизведения медленнее → {"action": "youtube_speed_down", "agent": true}
- Лайк видео на YouTube → {"action": "youtube_like", "agent": true}
- Найти видео/канал/плейлист на YouTube → {"action": "youtube_search:ЗАПРОС"}
- Популярное на YouTube → {"action": "youtube_trending"}

БРАУЗЕР (Opera GX) — управление через расширение:
- Новая вкладка, открыть новую → {"action": "browser:tab_new"}
- Закрыть вкладку, закрой это → {"action": "browser:tab_close"}
- Дублировать/скопировать вкладку → {"action": "browser:tab_dup"}
- Следующая вкладка → {"action": "browser:tab_next"}
- Предыдущая вкладка → {"action": "browser:tab_prev"}
- Обновить страницу, перезагрузи → {"action": "browser:tab_reload"}
- Назад → {"action": "browser:back"}
- Вперёд → {"action": "browser:forward"}
- Прокрутить вниз → {"action": "browser:scroll_down"}
- Прокрутить вверх → {"action": "browser:scroll_up"}
- Переключиться на вкладку с X (gmail, github, ютуб и т.д.) → {"action": "browser:switch:X"}
- Открыть сайт/URL → {"action": "browser:url:URL"}
- Найти/поискать что-то в браузере → {"action": "browser:search:ЗАПРОС"}
- Увеличить масштаб → {"action": "browser:zoom:in"}
- Уменьшить масштаб → {"action": "browser:zoom:out"}
- Нажать на кнопку/ссылку с текстом → {"action": "browser:click:ТЕКСТ"}
- Что на странице, прочитай страницу → {"action": "ext:page_content"}
- Что на ютубе, что за видео → {"action": "ext:page_content_youtube"}

ПРИЛОЖЕНИЯ:
- Открыть/запустить приложение или игру → {"action": "open_app", "arg": "НАЗВАНИЕ"}
- Закрыть приложение → {"action": "close_window:НАЗВАНИЕ"}

СИСТЕМА:
- Скриншот → {"action": "screenshot:"}
- Громче (с числом или без) → {"action": "volume_up:ЧИСЛО"} (число 0-100, по умолчанию 20)
- Тише (с числом или без) → {"action": "volume_down:ЧИСЛО"}
- Установить громкость → {"action": "volume:ЧИСЛО"}
- Игровой режим включить → {"action": "game_mode:on"}
- Игровой режим выключить → {"action": "game_mode:off"}

ВАЖНЫЕ ПРАВИЛА:
1. Используй контекст! Если играет музыка → «лайк» = music_like. Если открыт YouTube → «лайк» = youtube_like.
2. Если играет музыка → «следующий», «пауза», «стоп» относятся к музыке.
3. Если открыт YouTube → «пауза», «следующее» относятся к YouTube.
4. Вопросы, просьбы рассказать, «как дела», «который час», «что думаешь» → {"action": null}
5. Для ЗАПРОС/НАЗВАНИЕ/URL — извлеки из фразы пользователя
6. Неоднозначно без контекста → {"action": null}
7. say: НЕ использовать — это внутренняя команда
"""


def _preprocess(text: str) -> str:
    """
    Исправляет типичные STT-искажения перед отправкой в LLM.
    Только для часто искажаемых слов — не трогает смысл.
    """
    import difflib
    corrections = {
        "ключи": "включи",
        "клюй": "включи",
        "вклюй": "включи",
        "выклюй": "выключи",
        "баузер": "браузер",
        "брауза": "браузер",
        "доблируй": "дублируй",
        "задублируй": "дублируй",
        "следущий": "следующий",
        "слежующий": "следующий",
        "маузы": "пауза",
        "баузу": "паузу",
        "репит": "повтор",
        "ривайнд": "перемотка",
        "минеплэр": "мини-плеер",
        "минеплер": "мини-плеер",
        "минплеер": "мини-плеер",
        "а ей": "ai",
        "аей": "ai",
    }
    words = text.split()
    result = []
    for w in words:
        wl = w.lower().rstrip(".,!?")
        if wl in corrections:
            result.append(corrections[wl])
        else:
            result.append(w)
    return " ".join(result)


_HARDCODED = [
    # Музыка — запуск
    (["включи музыку", "запусти музыку", "поставь музыку", "врубай музыку",
      "включи яндекс", "запусти яндекс", "открой яндекс музыку",
      "хочу музыку", "музыку включи", "музон включи", "музон"],
     {"action": "open_app", "arg": "яндекс музыка"}),
    # Музыка — управление
    (["следующий трек", "следующую", "следующий", "дальше", "скип", "след трек"],
     {"action": "music_next"}),
    (["предыдущий трек", "предыдущий", "назад трек", "прошлый трек"],
     {"action": "music_prev"}),
    (["пауза", "стоп", "останови", "на паузу", "продолжи", "продолжай", "играй"],
     {"action": "music_play_pause"}),
    (["дизлайкни трек", "дизлайк трек", "не нравится трек"],
     {"action": "music_dislike"}),
    (["лайкни трек", "лайк трек", "добавь в любимые", "нравится трек"],
     {"action": "music_like"}),
    # Музыка — что играет
    (["что играет", "что сейчас играет", "что у меня играет", "что у меня сейчас играет",
      "какой трек", "какая песня", "что за музыка", "что за трек", "что слушаем"],
     {"action": "music_info"}),
    # Музыка — YM API воспроизведение
    (["мою волну", "моя волна", "волну включи", "включи волну", "включи мою волну"],
     {"action": "music_play_wave"}),
    (["дизлайкни", "дизлайк", "не нравится"],
     {"action": "music_dislike"}),
    (["лайкни", "лайк", "нравится", "понравилось"],
     {"action": "music_like"}),
    # Скриншот и зрение
    (["скриншот", "сделай скриншот", "снимок экрана", "скрин"],
     {"action": "screenshot:"}),
    (["что у меня на экране", "что на экране", "посмотри на экран",
      "что ты видишь", "опиши экран", "что происходит на экране",
      "что открыто", "что у меня открыто"],
     {"action": "screenshot:describe"}),
    # Громкость
    (["громче", "прибавь громкость", "сделай громче"],
     {"action": "volume_up:20"}),
    (["тише", "убавь громкость", "сделай тише"],
     {"action": "volume_down:20"}),
    # Браузер
    (["новая вкладка", "открой вкладку"],
     {"action": "browser:tab_new"}),
    (["закрой вкладку", "закрой таб"],
     {"action": "browser:tab_close"}),
    (["повтор", "повторяй", "репит", "repeat", "зациклить", "зацикли", "на репит", "поставь на повтор", "повтори трек"],
     {"action": "music:repeat"}),
    (["следующая вкладка", "следующий таб"],
     {"action": "browser:tab_next"}),
    (["предыдущая вкладка", "предыдущий таб"],
     {"action": "browser:tab_prev"}),
    (["обнови страницу", "обнови", "перезагрузи страницу"],
     {"action": "browser:tab_reload"}),
    (["прокрути вниз", "листай вниз"],
     {"action": "browser:scroll_down"}),
    (["прокрути вверх", "листай вверх"],
     {"action": "browser:scroll_up"}),
]


def _hardcoded_match(text: str) -> dict | None:
    """Хардкод для самых частых команд — работает без LLM."""
    stop = ["пожалуйста", "пожалуйст", "нам", "ка", "же", "ну"]
    tl = text.lower().strip().rstrip(".!?,")
    words = [w for w in tl.split() if w not in stop]
    tl_clean = " ".join(words)

    import re as _re

    # Сначала — точные фразы из _HARDCODED (высший приоритет)
    for phrases, action in _HARDCODED:
        for phrase in phrases:
            if tl_clean == phrase:
                return action
            if phrase in tl_clean:
                # Если текст длинный — фраза должна быть в начале (первые 30 символов),
                # иначе это не команда, а подстрока внутри длинного предложения
                pos = tl_clean.find(phrase)
                if len(tl_clean) < 40 or pos < 30:
                    return action

    return None


async def route_command(text: str, context: dict | None = None) -> dict | None:
    """
    Определяет команду по намерению через LLM.
    context: {"active_window": str, "current_track": dict, "youtube_open": bool}
    Возвращает dict {"action": ..., "arg": ..., "agent": ...} или None.
    """
    from config import get_active_key, mark_key_used, mark_key_rate_limited
    from google import genai
    from google.genai import types

    text = _preprocess(text)

    # Уровень 1 — пользовательский словарь (самый приоритетный)
    from modules.user_commands import match as user_match
    user_cmd = user_match(text)
    if user_cmd:
        log.info(f"[router] {text!r} → {user_cmd} (user dict)")
        return user_cmd

    # Уровень 2 — хардкод частых команд (без Gemini — работает без ключей)
    hard = _hardcoded_match(text)
    if hard:
        log.info(f"[router] {text!r} → {hard} (hardcoded)")
        return hard

    # Далее нужен Gemini — проверяем ключи
    key = get_active_key()
    if not key:
        return None

    # Уровень 3 — семантический фильтр (не гонять LLM зря)
    # Используем быструю проверку: если это вопрос/разговор без действия → пропускаем
    from modules.intent_classifier import is_command as _is_cmd, is_question as _is_q
    if _is_q(text) and not _is_cmd(text):
        return None

    # Формируем контекстную строку
    ctx_parts = []
    if context:
        aw = context.get("active_window", "")
        track = context.get("current_track", {})
        if track and track.get("title"):
            status = "играет" if track.get("status") == "playing" else "на паузе"
            ctx_parts.append(f"Музыка: {track.get('artist','')} — {track.get('title','')} ({status})")
        if "youtube" in aw.lower():
            ctx_parts.append("YouTube открыт и активен")
        elif aw:
            ctx_parts.append(f"Активное окно: {aw}")
    ctx_str = "\nТекущий контекст: " + "; ".join(ctx_parts) if ctx_parts else ""
    prompt = f'Пользователь сказал: "{text}"{ctx_str}\n\nДействие:'  

    for _attempt in range(5):
        key = get_active_key()
        if not key:
            return None
        try:
            client = genai.Client(api_key=key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.1-flash-lite",
                contents=[types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)]
                )],
                config=types.GenerateContentConfig(
                    system_instruction=INTENTS_PROMPT,
                    temperature=0.0,
                    max_output_tokens=80,
                )
            )
            mark_key_used(key)
            raw = (response.text or "").strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            result = json.loads(raw)
            if not result.get("action"):
                return None
            log.info(f"[router] {text!r} → {result}")
            return result
        except json.JSONDecodeError:
            log.debug(f"[router] JSON parse error: {raw!r}")
            return None
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "exhausted" in err.lower():
                log.warning(f"[router] 429, пропускаю (keys не блокирую)")
                return None
            log.debug(f"[router] error: {e}")
            return None
    return None


# ── Критические команды — только точный матчинг ───────────────────────

_CRITICAL_EXACT = {
    "выключи компьютер":      "system:shutdown",
    "выключи пк":             "system:shutdown",
    "выключи ноутбук":        "system:shutdown",
    "перезагрузи компьютер":  "system:restart",
    "перезагрузи пк":         "system:restart",
    "заблокируй компьютер":   "system:lock",
    "заблокируй экран":       "system:lock",
    "заблокируй пк":          "system:lock",
    "спящий режим":           "system:sleep",
    "сон компьютера":         "system:sleep",
    "вскипяти чайник":        "kettle:boil",
    "включи чайник":          "kettle:boil",
    "поставь чайник":         "kettle:boil",
    "выключи чайник":         "kettle:off",
    "останови чайник":        "kettle:off",
    "статус чайника":         "kettle:status",
}


def route_critical(text: str) -> str | None:
    """Точный матчинг критических команд. Проверяется до LLM-роутера."""
    tl = text.lower().strip().rstrip(".?!")

    if tl in _CRITICAL_EXACT:
        return _CRITICAL_EXACT[tl]

    m = re.search(r"нагрей.*?(\d+)\s*градус", tl)
    if m and "чайник" in tl:
        temp = max(40, min(95, int(m.group(1))))
        return f"kettle:heat:{temp}"

    return None