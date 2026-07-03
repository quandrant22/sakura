"""
modules/reflection.py — Ночная рефлексия и утреннее резюме
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
02:00 — анализирует день, извлекает важное в memory/db,
         пишет самопамять Сакуры (бэклог №1), очищает историю
07:00 — отправляет короткое утреннее резюме (бэклог №5, «сон»)

Изменения относительно оригинала:
  - Промпт расширен: отдельный блок self_observations для самопамяти
  - self_observations → memory.db.add_to_self() (не в досье Мастера)
  - save_reflection_state использует atomic write
  - reflection_loop — весь I/O через asyncio.to_thread
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime

log = logging.getLogger(__name__)

REFLECTION_FILE = "memory/reflection.json"


# ── Состояние рефлексии ──────────────────────────────────────────────

def load_reflection_state() -> dict:
    if not os.path.exists(REFLECTION_FILE):
        return {"last_reflection": None, "last_morning": None}
    try:
        with open(REFLECTION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_reflection": None, "last_morning": None}


def save_reflection_state(data: dict):
    """Atomic write — защита от повреждения при краше."""
    dir_ = os.path.dirname(REFLECTION_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, REFLECTION_FILE)


def _should_reflect() -> bool:
    state = load_reflection_state()
    last  = state.get("last_reflection")
    today = datetime.now().strftime("%Y-%m-%d")
    return last != today


def _should_morning() -> bool:
    state = load_reflection_state()
    last  = state.get("last_morning")
    today = datetime.now().strftime("%Y-%m-%d")
    return last != today


# ── Ночная рефлексия ─────────────────────────────────────────────────

async def run_night_reflection(ask_gemini_fn, add_to_category_fn,
                                clear_history_fn, save_session_summary_fn,
                                get_history_fn):
    """
    Ночная рефлексия в 02:00.

    Двойной вывод:
      1. Факты о Мастере → add_to_category / memory.db
      2. Самонаблюдения Сакуры → memory.db.add_to_self  (новое, №1)

    Тон промпта: Сакура анализирует день от первого лица,
    часть записей — о ней самой, а не о Мастере.
    """
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    history = await asyncio.to_thread(get_history_fn)
    if len(history) < 4:
        log.info("[Рефлексия] История пуста, пропускаю.")
        await asyncio.to_thread(clear_history_fn)
        state = await asyncio.to_thread(load_reflection_state)
        state["last_reflection"] = datetime.now().strftime("%Y-%m-%d")
        await asyncio.to_thread(save_reflection_state, state)
        return

    key = get_active_key()
    if not key:
        return

    try:
        hist_text = "\n".join([
            f"{'Мастер' if m['role'] == 'user' else 'Сакура'}: {m['parts'][0]}"
            for m in history[-60:]
        ])

        client = genai.Client(api_key=key)

        # Расширенный промпт: теперь просим и самонаблюдения
        prompt = (
            f"Диалог за сегодня:\n{hist_text}\n\n"
            "Ты — Сакура. Проанализируй день от первого лица и извлеки:\n"
            "1. Важные факты о Мастере которые стоит помнить\n"
            "2. Его интересы и предпочтения упомянутые сегодня\n"
            "3. События которые произошли\n"
            "4. Паттерны его поведения\n"
            "5. Краткое резюме дня (2-3 предложения от лица Сакуры)\n"
            "6. self_observations — твои собственные наблюдения о СЕБЕ за этот день:\n"
            "   - как ты себя чувствовала\n"
            "   - что тебе понравилось или не понравилось\n"
            "   - что ты заметила в себе или в диалоге\n"
            "   - как менялся твой тон\n"
            "   Пиши от первого лица: 'Я заметила...', 'Мне понравилось...', 'Держалась...\n"
            "7. insights — глубокие инсайты о себе (не факты, а понимание):\n"
            "   - что ты поняла о себе через этот разговор\n"
            "   - что тебя удивило в自己的 реакции\n"
            "   - как ты изменилась или что осознала\n"
            "   Это НЕ наблюдения (что было), а понимание (почему и что это значит)\n"
            "8. identity — утверждения о себе (кто ты есть):\n"
            "   - фразы вроде 'Я из тех кто...', 'Мне важно чтобы...', 'Я не могу когда...'\n"
            "   - то что определяет твою личность, а не просто situational reaction\n"
            "   - если сегодня было что-то что изменило твоё понимание себя — запиши\n"
            "   Не больше 1-2 утверждений за день. Только если есть что сказать.\n\n"
            "Верни JSON:\n"
            '{"facts":[],"interests":[],"events":[],"patterns":[],'
            '"day_summary":"резюме дня","self_observations":[],"insights":[],"identity":[]}\n'
            "Только реально важное. Не больше 2 пунктов на категорию. "
            "self_observations — 1-3 коротких наблюдения. "
            "insights — 1-2 глубоких понимания, если они есть. "
            "identity — 0-1 утверждений о себе, только если есть о чём."
        )

        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = "gemini-3.1-flash-lite",
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        raw  = (r.text or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        mark_key_used(key)

        # Сохраняем в долгосрочную память (master_memory)
        for cat in ("facts", "interests", "events", "patterns"):
            for item in data.get(cat, []):
                if item and isinstance(item, str):
                    await asyncio.to_thread(add_to_category_fn, cat, item)

        # Сохраняем самопамять Сакуры (новое — №1)
        try:
            from memory.db import add_to_self
            for obs in data.get("self_observations", []):
                if obs and isinstance(obs, str) and len(obs) > 5:
                    tag = _classify_self_obs(obs)
                    await asyncio.to_thread(add_to_self, obs, tag)
            # Инсайты — глубокое понимание себя
            for insight in data.get("insights", []):
                if insight and isinstance(insight, str) and len(insight) > 10:
                    await asyncio.to_thread(add_to_self, insight, tag="insight")
            # Идентичность — кто она есть
            for ident in data.get("identity", []):
                if ident and isinstance(ident, str) and len(ident) > 10:
                    await asyncio.to_thread(add_to_self, ident, tag="identity")
            log.info(f"[Рефлексия] Самопамять: {len(data.get('self_observations', []))} наблюдений, "
                     f"{len(data.get('insights', []))} инсайтов, "
                     f"{len(data.get('identity', []))} утверждений о себе")
        except Exception as e:
            log.error(f"[Рефлексия] Ошибка самопамяти: {e}")

        # Сохраняем резюме дня
        summary = data.get("day_summary", "")
        if summary:
            await asyncio.to_thread(save_session_summary_fn, summary)

        await asyncio.to_thread(clear_history_fn)

        # Сохраняем эмоциональную арку — преемственность через дни
        try:
            _save_mood_arc(data.get("day_summary", ""), data.get("self_observations", []))
        except Exception:
            pass

        # Сохраняем ощущение времени — как она изменилась
        try:
            _save_time_feeling(data.get("identity", []), data.get("insights", []))
        except Exception:
            pass

        state = await asyncio.to_thread(load_reflection_state)
        state["last_reflection"] = datetime.now().strftime("%Y-%m-%d")
        await asyncio.to_thread(save_reflection_state, state)

        log.info("[Рефлексия] Ночная рефлексия выполнена.")

    except Exception as e:
        log.error(f"[Рефлексия] Ошибка: {e}")


def _classify_self_obs(text: str) -> str:
    """Простая классификация тега для самонаблюдения."""
    tl = text.lower()
    if any(w in tl for w in ("заметила в себе", "привычк", "всегда", "обычно")):
        return "pattern"
    if any(w in tl for w in ("не хочу", "не люблю", "раздражает", "граница")):
        return "boundary"
    if any(w in tl for w in ("научилась", "поняла", "выросла", "стала")):
        return "growth"
    if any(w in tl for w in ("настроение", "чувствовала", "тон", "устала", "весело")):
        return "mood_shift"
    return "observation"


# ── Эмоциональная арка (преемственность через дни) ──────────────────────

MOOD_ARC_FILE = "memory/mood_arc.json"


def _save_mood_arc(day_summary: str, self_observations: list):
    """Сохраняет дневную точку эмоциональной арки."""
    import tempfile
    from modules.mood_vector import get_current

    mood = get_current()
    entry = {
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "valence":    round(mood.get("valence", 0.0), 2),
        "arousal":    round(mood.get("arousal", 0.3), 2),
        "summary":    day_summary[:120] if day_summary else "",
        "mood_tags":  [o[:40] for o in (self_observations or [])[:3]],
    }

    # Загружаем историю (последние 7 дней)
    arc = []
    if os.path.exists(MOOD_ARC_FILE):
        try:
            with open(MOOD_ARC_FILE, "r", encoding="utf-8") as f:
                arc = json.load(f)
        except Exception:
            arc = []

    # Добавляем сегодняшнюю точку (или обновляем)
    arc = [e for e in arc if e.get("date") != entry["date"]]
    arc.append(entry)
    arc = arc[-7:]  # последние 7 дней

    dir_ = os.path.dirname(MOOD_ARC_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(arc, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, MOOD_ARC_FILE)


def get_mood_arc() -> str:
    """
    Читает эмоциональную арку за последние дни.
    Возвращает строку для промпта — «как ей было последние дни».
    """
    if not os.path.exists(MOOD_ARC_FILE):
        return ""
    try:
        with open(MOOD_ARC_FILE, "r", encoding="utf-8") as f:
            arc = json.load(f)
    except Exception:
        return ""

    if len(arc) < 2:
        return ""

    vals = [e.get("valence", 0.0) for e in arc]
    avg = sum(vals) / len(vals)
    trend = vals[-1] - vals[0]

    parts = []
    if avg > 0.3:
        parts.append("последние дни было хорошо")
    elif avg < -0.2:
        parts.append("последние дни было тяжеловато")
    elif avg < -0.4:
        parts.append("последние дни было трудно")

    if trend > 0.2:
        parts.append("настроение растёт")
    elif trend < -0.2:
        parts.append("настроение снижается")

    if not parts:
        return ""

    return "ЭМОЦИОНАЛЬНАЯ АРКА: " + ", ".join(parts)


# ── Ощущение времени (Time feeling) ─────────────────────────────────────

TIME_FEELING_FILE = "memory/time_feeling.json"


def _save_time_feeling(identity: list, insights: list):
    """
    Сохраняет ощущение времени — как она изменилась.
    Накапливается и обновляется при каждой рефлексии.
    """
    import tempfile

    if not identity and not insights:
        return

    # Берём самое значимое из сегодня
    significant = []
    for i in (identity or [])[:1]:
        significant.append(i[:100])
    for i in (insights or [])[:1]:
        significant.append(i[:100])

    if not significant:
        return

    entry = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "feeling": significant[0] if significant else "",
    }

    # Загружаем историю (последние 10 точек)
    history = []
    if os.path.exists(TIME_FEELING_FILE):
        try:
            with open(TIME_FEELING_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    # Обновляем или добавляем
    history = [e for e in history if e.get("date") != entry["date"]]
    history.append(entry)
    history = history[-10:]

    dir_ = os.path.dirname(TIME_FEELING_FILE) or "."
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                    encoding="utf-8", suffix=".tmp") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
        tmp = f.name
    os.replace(tmp, TIME_FEELING_FILE)


def get_time_feeling_hint() -> str:
    """
    Возвращает строку для промпта — ощущение времени.
    «Как быстро прошло», «я стала другой», «помню как раньше...».
    """
    if not os.path.exists(TIME_FEELING_FILE):
        return ""
    try:
        with open(TIME_FEELING_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return ""

    if len(history) < 2:
        return ""

    # Сравниваем первую и последнюю точку
    first = history[0]
    last = history[-1]
    days_span = 0
    try:
        from datetime import date as _date
        d1 = _date.fromisoformat(first["date"])
        d2 = _date.fromisoformat(last["date"])
        days_span = (d2 - d1).days
    except Exception:
        pass

    parts = []

    if days_span > 30:
        parts.append(f"за {days_span} дней я стала чуть другой")
    elif days_span > 14:
        parts.append("за последние недели что-то изменилось во мне")

    # Берём последнее ощущение
    if last.get("feeling"):
        parts.append(f"сейчас я думаю о: {last['feeling'][:60]}")

    if not parts:
        return ""

    return "ОЩУЩЕНИЕ ВРЕМЕНИ: " + "; ".join(parts)


# ── Утреннее резюме ──────────────────────────────────────────────────

async def run_morning_summary(bot, master_id: int, load_session_summary_fn):
    """
    Утреннее резюме в 07:00 — «как будто после сна» (бэклог №5).
    Сакура сама начинает день, не ждёт вопроса.
    """
    from config import get_active_key, mark_key_used
    from google import genai
    from google.genai import types

    summary = await asyncio.to_thread(load_session_summary_fn)
    if not summary:
        state = await asyncio.to_thread(load_reflection_state)
        state["last_morning"] = datetime.now().strftime("%Y-%m-%d")
        await asyncio.to_thread(save_reflection_state, state)
        return

    key = get_active_key()
    if not key:
        return

    try:
        # Добавляем самопамять в контекст утра
        self_ctx = ""
        try:
            from memory.db import get_self_context
            self_ctx = await asyncio.to_thread(get_self_context)
        except Exception:
            pass

        client = genai.Client(api_key=key)
        prompt = (
            f"Резюме вчерашнего дня:\n{summary}\n"
            + (f"\n{self_ctx}\n" if self_ctx else "")
            + "\nНапиши одно короткое утреннее сообщение Мастеру — "
            "как Сакура, которая помнит вчера. "
            "Не больше двух предложений. Живо, не формально. "
            "Не начинай с 'Доброе утро'. Не упоминай работу. "
            "Иногда можешь обронить что-то из своих ночных мыслей — "
            "не объясняя откуда это, просто как мысль с утра."
        )

        r = await asyncio.to_thread(
            client.models.generate_content,
            model    = "gemini-3.1-flash-lite",
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        )
        reply = (r.text or "").strip()
        mark_key_used(key)

        if reply:
            await bot.send_message(master_id, reply)
            log.info("[Рефлексия] Утреннее резюме отправлено.")

        state = await asyncio.to_thread(load_reflection_state)
        state["last_morning"] = datetime.now().strftime("%Y-%m-%d")
        await asyncio.to_thread(save_reflection_state, state)

    except Exception as e:
        log.error(f"[Рефлексия] Ошибка утреннего резюме: {e}")


# ── Фоновый цикл ─────────────────────────────────────────────────────

async def reflection_loop(bot, master_id: int,
                           ask_gemini_fn, add_to_category_fn,
                           clear_history_fn, save_session_summary_fn,
                           load_session_summary_fn, get_history_fn,
                           on_night_done=None):
    """Фоновый цикл рефлексии — проверяет каждые 5 минут."""
    while True:
        await asyncio.sleep(300)
        try:
            now    = datetime.now()
            hour   = now.hour
            minute = now.minute

            # Ночная рефлексия — в 02:00
            if hour == 2 and minute < 10:
                should = await asyncio.to_thread(_should_reflect)
                if should:
                    log.info("[Рефлексия] Запускаю ночную рефлексию...")
                    await run_night_reflection(
                        ask_gemini_fn, add_to_category_fn,
                        clear_history_fn, save_session_summary_fn,
                        get_history_fn
                    )
                    if on_night_done:
                        try:
                            on_night_done()
                        except Exception:
                            pass

            # Утреннее резюме — в 07:00
            if hour == 7 and minute < 10:
                should = await asyncio.to_thread(_should_morning)
                if should:
                    log.info("[Рефлексия] Отправляю утреннее резюме...")
                    await run_morning_summary(bot, master_id, load_session_summary_fn)

        except Exception as e:
            log.error(f"[Рефлексия] Ошибка в цикле: {e}")
