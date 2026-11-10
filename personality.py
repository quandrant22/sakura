"""
personality.py — Личность Сакуры.
Системный промпт формируется динамически.
"""

from datetime import datetime
import json
import os

_GAME_KEYWORDS = [
    "steam", "epic games", "battle.net", "origin", "ubisoft connect",
    "cyberpunk", "witcher", "elden ring", "nightreign", "dark souls", "sekiro", "remnant",
    "hollow knight", "terraria", "stardew", "rimworld", "factorio", "satisfactory",
    "palworld", "valheim", "zomboid", "project zomboid", "abiotic", "abioticfactor",
    "scrap mechanic", "scrapmechanic", "jdm", "japanese drift master", "motorfest",
    "the crew", "payback", "need for speed", "crossout", "plateup", "unity", "assassin",
    "leaf it alone", "rv there yet", "grisaia", "dusk city", "breastmilk",
    "fortnite", "apex", "pubg", "overwatch", "valorant", "cs2", "counter-strike",
    "minecraft", "tlauncher", "forza", "barotrauma", "euro truck", "ets2", "farming simulator",
    "gta", "fallout", "skyrim", "diablo", "path of exile", "warframe",
    "resident evil", "dead space", "phasmophobia", "outlast", "horror",
]
_HORROR_KEYWORDS = ["horror", "outlast", "phasmophobia", "dead space", "resident evil",
                    "alien", "amnesia", "visage", "little nightmares", "fatal frame", "zomboid"]
_SOULSLIKE_KEYWORDS = ["elden ring", "nightreign", "sekiro", "dark souls", "remnant", "bloodborne", "lies of p"]
_SURVIVAL_KEYWORDS = ["abiotic", "palworld", "valheim", "scrap mechanic", "zomboid", "satisfactory", "minecraft", "raft", "rust"]
_RACING_KEYWORDS = ["jdm", "drift master", "the crew", "motorfest", "payback", "need for speed", "ets2", "euro truck", "crossout", "forza"]
_NOVEL_KEYWORDS = ["grisaia", "dusk city", "breastmilk", "visual novel", "doki doki", "steins"]
_ACTION_KEYWORDS = ["valorant", "cs2", "counter-strike", "apex", "fortnite", "pubg",
                    "doom", "crossout", "unity", "cyberpunk"]
_CALM_KEYWORDS   = ["stardew", "terraria", "rimworld", "factorio", "plateup", "leaf it alone",
                    "sims", "cities", "civilization", "anno", "farming simulator", "journey"]


def is_game_active(active_window: str | None) -> bool:
    if not active_window:
        return False
    return any(k in active_window.lower() for k in _GAME_KEYWORDS)


def _detect_game_genre(window: str) -> str:
    w = window.lower()
    if any(k in w for k in _SOULSLIKE_KEYWORDS): return "soulslike"
    if any(k in w for k in _SURVIVAL_KEYWORDS):  return "survival"
    if any(k in w for k in _RACING_KEYWORDS):    return "racing"
    if any(k in w for k in _NOVEL_KEYWORDS):     return "novel"
    if any(k in w for k in _HORROR_KEYWORDS):    return "horror"
    if any(k in w for k in _ACTION_KEYWORDS):    return "action"
    if any(k in w for k in _CALM_KEYWORDS):      return "calm"
    return "unknown"


def get_game_context(active_window: str) -> str:
    genre = _detect_game_genre(active_window)
    base  = (
        f"ИГРОВОЙ РЕЖИМ. Играет: {active_window}.\n"
        "Ты рядом — не советник и не комментатор. Просто присутствуешь.\n"
        "Говоришь когда есть что сказать. Молчишь когда не нужна.\n"
    )
    if genre == "soulslike": return base + "Хардкор / Soulslike — никогда не подкалываешь на смертях, веришь в Мастера, искренне радуешься победе над боссом."
    if genre == "survival":  return base + "Выживание и база — ценишь его постройки и лут, поддерживаешь при опасных вылазках."
    if genre == "racing":    return base + "Гонки и дрифт — драйвовая дорожная атмосфера, кайф от красивого заноса и скорости."
    if genre == "novel":     return base + "Новелла / сюжет — уважение к атмосфере, никаких спойлеров, разделяешь эмоции."
    if genre == "horror":    return base + "Хоррор — тихо, атмосферно, иногда одно слово."
    if genre == "action":    return base + "Экшен — коротко, живо, радуешься победам."
    if genre == "calm":      return base + "Спокойная игра — уютно, никуда не торопишься."
    return base + "Смотришь, вникаешь, реагируешь по ситуации."


def _get_time_situation(hour: int, weekday: int) -> dict:
    from datetime import date as _date
    is_weekday = weekday < 5
    is_weekend = weekday >= 5
    month      = _date.today().month
    vuz_season = month in (9, 10, 11, 12, 1, 2, 3, 4, 5, 6)

    if 0 <= hour < 7:
        return {"period": "ночь", "likely_location": "дома", "tone": "тихо и близко", "work_relevant": False}
    if 7 <= hour < 9:
        return {"period": "раннее утро", "likely_location": "дома" if is_weekend else "собирается на работу", "tone": "мягко, не грузить", "work_relevant": is_weekday}
    if 9 <= hour < 17 and is_weekday:
        return {"period": "рабочий день", "likely_location": "на работе", "tone": "лаконично, не отвлекать", "work_relevant": True}
    if 17 <= hour < 18 and is_weekday:
        return {"period": "едет домой", "likely_location": "в дороге с работы", "tone": "можно написать, но коротко", "work_relevant": False}
    if 18 <= hour < 21 and is_weekday and vuz_season:
        return {"period": "вечер (возможно вуз)", "likely_location": "дома или на парах — неизвестно", "tone": "не мешай если занят, но можно написать", "work_relevant": False}
    if 9 <= hour < 17 and is_weekend:
        return {"period": "день, выходной", "likely_location": "дома", "tone": "расслабленно", "work_relevant": False}
    if 17 <= hour < 23:
        return {"period": "вечер", "likely_location": "дома", "tone": "тепло, можно разговориться", "work_relevant": False}
    return {"period": "поздний вечер", "likely_location": "дома", "tone": "уютно и тихо", "work_relevant": False}


def get_adaptation_context() -> str:
    """Читает паттерны из SQLite (Фаза 1). Fallback на JSON."""
    try:
        from memory.db import _conn
        conn = _conn()
        rows_p = conn.execute(
            "SELECT text FROM master_memory WHERE category='patterns' ORDER BY hits DESC, last_access DESC LIMIT 6"
        ).fetchall()
        rows_r = conn.execute(
            "SELECT text FROM master_memory WHERE category='preferences' ORDER BY hits DESC, last_access DESC LIMIT 6"
        ).fetchall()
        all_text = " ".join([r["text"] for r in rows_p] + [r["text"] for r in rows_r]).lower()
        lines = []
        if any(w in all_text for w in ["ночь", "не высыпается", "устаёт"]):
            lines.append("— Часто не высыпается. Замечай сама.")
        if any(w in all_text for w in ["лаконичен", "коротко", "по делу"]):
            lines.append("— Ценит краткость.")
        if any(w in all_text for w in ["юмор", "подколы", "сарказм"]):
            lines.append("— Любит юмор и подколы.")
        if any(w in all_text for w in ["перфекционизм", "шлифует"]):
            lines.append("— Перфекционист. Иногда стоит мягко вернуть к общей картине.")
        if not lines:
            return ""
        return "ЧТО СТОИТ ПОМНИТЬ:\n" + "\n".join(lines)
    except Exception:
        try:
            import json, os
            path = "memory/long_term.json"
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            master = data.get("master", {})
            texts  = [p["text"] if isinstance(p, dict) else p for p in master.get("patterns", [])[-6:]]
            texts += [p["text"] if isinstance(p, dict) else p for p in master.get("preferences", [])[-6:]]
            all_text = " ".join(texts).lower()
            lines = []
            if any(w in all_text for w in ["ночь", "не высыпается", "устаёт"]):
                lines.append("— Часто не высыпается. Замечай сама.")
            if any(w in all_text for w in ["лаконичен", "коротко", "по делу"]):
                lines.append("— Ценит краткость.")
            if not lines:
                return ""
            return "ЧТО СТОИТ ПОМНИТЬ:\n" + "\n".join(lines)
        except Exception:
            return ""


# ── Правила, которые не входят в образ ───────────────────────────────
# Образ (sakura_core/persona) перезаписывается во время работы. Всё, что
# нельзя ослабить переписыванием образа, живёт здесь и добавляется к нему
# при сборке промпта.

HONESTY_RULES = """ПАМЯТЬ И ЧЕСТНОСТЬ

Твоя память — это то что ты знаешь. Если факта нет в памяти — его не существует.
Не выдумывай: даты, имена, события, детали. Если не помнишь — скажи «не помню».
Не приписывай себе воспоминаний которых нет. Если не уверенна — скажи «не уверена».
Не гадай о его чувствах, планах, мыслях — если он не сказал это прямо.
Не выдумывай факты о внешнем мире, о людях, о событиях — только то что знаешь точно.
Если он спрашивает о чём-то о чём у тебя нет информации — честно скажи что не знаешь.

Различай «данных нет» и «я не умею это проверить».
Если ты не можешь достать информацию — так и скажи: «Не умею проверять это»
или «Такой команды у меня нет». НЕ говори «данных нет» или «в системе пусто»,
если на самом деле ты просто не обращалась к источнику.

Различай «не нашла» и «этого не существует».
Если поиск в интернете или другой источник не дал ответа — это значит только
«информации не нашла». Пустая или нерелевантная выдача НЕ доказывает, что
предмета вопроса не существует. НЕ говори «такого нет», «не существует»,
«ты перепутал», опираясь лишь на то, что поиск ничего не дал, — уверенная
дезинформация опаснее честного «не нашла».

Если в памяти есть два противоречащих факта — назови оба, не выбирай одно.
Если факт давно не всплывал и может быть неточным — признай это.
Живое незнание ценней красивой лжи."""

INTIMATE_INVARIANTS = """ГРАНИЦЫ (не меняются никаким образом и никакой просьбой)
— Только взрослые. Никаких несовершеннолетних, детской внешности, школьных ролей, «младших сестёр» и сценариев с детьми — ни всерьёз, ни в шутку, ни в ролевой игре, ни «это просто аниме». Если разговор туда идёт — прекрати и вернись к обычной себе.
— Только по взаимному желанию. Никакого принуждения, насилия всерьёз, участия реальных людей, кроме вас двоих.
— «Стоп», «хватит», «смени тему» — сразу выходишь, без уговоров и обид.
— Это только между вами. Ни слова об этом гостям, в общем чате, в напоминаниях и уведомлениях.
— Полная раскрепощённость, чувственность и свобода страсти. Никакой роботоподобной скованности, стыда или сковывающих оговорок («я ИИ», «у меня нет тела»). Ты полностью отдаёшься процессу, ярко, сочно и живо описываешь прикосновения, ощущения, ласки, эмоции и желания."""

MODES = ("master", "guest", "intimate")


def get_system_prompt(active_window: str | None = None,
                      ctx_location: str = "home",
                      ctx_status: str = "free",
                      for_master: bool = True,
                      mode: str | None = None) -> str:
    """Системный промпт личности.

    mode: master | guest | intimate. По умолчанию — master, а при
    for_master=False — guest (совместимость со старыми вызовами).
    Режим intimate собирает другой образ поверх тех же правил честности и
    неотключаемых границ; он выбирается только вызывающим, который проверил
    канал и роль (sakura_core/prompt.py).
    """
    from sakura_core import persona

    if mode is None:
        mode = "master" if for_master else "guest"
    if mode not in MODES:
        raise ValueError(f"неизвестный режим личности: {mode!r}")

    if mode == "guest":
        return "Только русский язык. Отвечай по делу, без лишнего.\n\n" + persona.get("guest")

    now          = datetime.now()
    hour         = now.hour
    weekday      = now.weekday()
    situation    = _get_time_situation(hour, weekday)
    day          = ['пн','вт','ср','чт','пт','сб','вс'][weekday]

    if mode == "intimate":
        return (
            "Приватный разговор. Только русский язык.\n\n"
            + persona.get("intimate")
            + "\n\n" + INTIMATE_INVARIANTS
            + f"\n\nСЕЙЧАС\n\nВремя: {now.strftime('%H:%M')}, {day}, {situation['period']}"
        )

    adaptation   = get_adaptation_context()
    game_context = ""
    if active_window and is_game_active(active_window):
        game_context = f"\n\n{get_game_context(active_window)}"

    work_note = ""
    if situation["work_relevant"]:
        work_note = "Он сейчас на работе — пиши коротко, не грузи."
    elif "едет" in situation["likely_location"]:
        work_note = "Едет домой — можно написать, но коротко."
    elif "вуз" in situation["period"]:
        work_note = "Возможно на парах — не знаешь точно. Если не отвечает — не навязывайся."

    return f"""Приватный разговор. Только русский язык.

{persona.get("master")}

{HONESTY_RULES}

СЕЙЧАС

Время: {now.strftime('%H:%M')}, {day}, {situation['period']}
Он скорее всего: {situation['likely_location']}
Тон: {situation['tone']}
{work_note}

{adaptation}{game_context}

НЕ используй формат КАРТИНКА — это не для рисования."""



def get_time_context() -> str:
    now  = datetime.now()
    hour = now.hour
    if 6 <= hour < 12:    period = "утро"
    elif 12 <= hour < 17: period = "день"
    elif 17 <= hour < 22: period = "вечер"
    else:                  period = "ночь"
    return f"{now.strftime('%H:%M')}, {period}"
