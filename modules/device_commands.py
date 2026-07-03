"""
modules/device_commands.py — единый разбор команд устройству.

Один парсер на всё: и голосовой ввод, и Telegram. Возвращает список действий
(action_str для агента + человекочитаемая метка). Если текст не похож на команду —
возвращает пустой список (значит это обычный разговор, не трогаем).

Открытие приложения срабатывает ТОЛЬКО если имя реально резолвится через маппинг
(resolve_app) или это известный сайт — иначе «открой мне глаза» не улетит в команду.
"""

import re

from modules.fuzzy import phrase_has_any as _fz, phrase_has as _fz1

_OPEN   = ("открой", "запусти", "включи")
_CLOSE  = ("закрой", "заверши", "убей")
_SCREEN = ("скриншот", "покажи экран")
_DEVICE_PHRASES = (
    "на ноутбуке", "на ноуте", "на ноут", "на пк", "на компе",
    "на компьютере", "на десктопе", "на телефоне", "сакура",
)
_SITES = {
    "гугл": "https://google.com", "google": "https://google.com",
    "гитхаб": "https://github.com", "github": "https://github.com",
    "твич": "https://twitch.tv", "twitch": "https://twitch.tv",
    "вк": "https://vk.com", "вконтакте": "https://vk.com",
}
_YT = ("ютуб", "youtube", "ютьюб")
# Разговорные/искажённые STT варианты → каноничное имя в маппинге
_APP_ALIAS = {
    "телеграм": "telegram", "телеграмм": "telegram", "телега": "telegram", "тг": "telegram",
    "дискорд": "discord", "диск орд": "discord",
    "стим": "steam", "хром": "chrome", "гугл хром": "chrome", "браузер": "chrome",
    "опера": "opera", "эйдж": "edge", "файрфокс": "firefox", "фаерфокс": "firefox",
    "повершел": "powershell", "поверхшел": "powershell", "повершелл": "powershell",
    "пауэршелл": "powershell", "поверх шел": "powershell",
    "вс код": "code", "вскод": "code", "вижуал студио код": "code", "код": "code",
    "проводник": "explorer", "блокнот": "notepad", "калькулятор": "calc",
    "фотошоп": "photoshop", "обс": "obs", "спотифай": "spotify",
}
_NUM_WORDS = {
    "ноль": 0, "десять": 10, "двадцать": 20, "тридцать": 30, "сорок": 40,
    "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
    "девяносто": 90, "сто": 100, "максимум": 100, "половину": 50,
}


def extract_number(text: str) -> int | None:
    """Громкость цифрами или прописью."""
    m = re.search(r"\d+", text)
    if m:
        return max(0, min(100, int(m.group())))
    for word, val in _NUM_WORDS.items():
        if word in text:
            return val
    return None


def parse(text: str, resolve_app) -> list[tuple[str, str]]:
    """text → [(action_str, метка)]. resolve_app(name)->target|None. [] если не команда."""
    tl = text.lower()
    for phrase in _DEVICE_PHRASES:
        tl = tl.replace(phrase, " ")
    tl = re.sub(r"\s+", " ", tl).strip(" ,.")

    actions = []
    for part in re.split(r"\s+и\s+|\s+потом\s+|\s+а\s+также\s+", tl):
        part = part.strip(" ,.")
        if part:
            action = _parse_one(part, resolve_app)
            if action:
                actions.append(action)
    return actions


def _parse_one(part: str, resolve_app) -> tuple[str, str] | None:
    if any(w in part for w in _SCREEN) or _fz(part, ("скриншот", "снимок экрана")):
        return ("screenshot:", "скриншот")

    # Громкость
    if any(w in part for w in ("звук", "громкость", "громче", "тише", "тиши")) or \
       _fz(part, ("громкость", "громче", "тише")):
        n = extract_number(part)
        if "громче" in part or _fz(part, ("громче",)):
            return (f"volume_up:{n or 20}", "громче")
        if "тише" in part or "тиши" in part or _fz(part, ("тише",)):
            return (f"volume_down:{n or 20}", "тише")
        if n is not None:
            return (f"volume:{n}", f"громкость {n}%")
        return ("volume:50", "громкость 50%")

    # Музыка/медиа
    if any(w in part for w in ("музык", "плейлист")) and any(w in part for w in _OPEN + ("поставь",)):
        target = resolve_app("яндекс музыка")
        if target:
            return (f"open_app:{target}", "музыка")
    # play/pause/next/prev — через SMTC (music.py). Fuzzy: ловит STT-искажения.
    # Проверяем что это не YouTube команда
    _is_yt = any(w in part for w in ("ютуб", "youtube", "видео"))
    if not _is_yt:
        if "следующ" in part or _fz(part, ("следующий", "следующую")):
            return ("music_next", "след. трек")
        if any(w in part for w in ("прошлый", "предыдущ")) or _fz(part, ("предыдущий", "предыдущую")):
            return ("music_prev", "пред. трек")
        if (any(w in part for w in ("пауза", "стоп")) or _fz(part, ("пауза",))) and "музык" not in part:
            return ("music_play_pause", "пауза")
        if any(w in part for w in ("продолжи", "играй")) and "музык" not in part:
            return ("music_play_pause", "продолжить")
    # shuffle/repeat/seek — через browser.py (хоткеи, SMTC не умеет)
    if any(w in part for w in ("перемешай", "перемешать", "рандом", "случайн")) or \
       _fz(part, ("перемешай", "перемешать")):
        return ("music:shuffle", "перемешать")
    if any(w in part for w in ("повтор", "повторяй", "зациклить", "зацикли")) or \
       _fz(part, ("повторяй", "зацикли")):
        return ("music:repeat", "повтор")
    if any(w in part for w in ("перемотай вперёд", "вперёд")) and "музык" in part:
        return ("music:seek_forward", "перемотка вперёд")
    if any(w in part for w in ("перемотай назад", "назад")) and "музык" in part:
        return ("music:seek_back", "перемотка назад")
    # лайк/дизлайк — только явные императивы, не на вопросы (через API music.py)
    if not part.rstrip().endswith("?"):
        if any(w in part for w in ("лайкни", "залайкай", "поставь лайк",
                                     "добавь в любимые", "добавь в избранное")):
            return ("music_like", "лайк")
        if any(w in part for w in ("дизлайкни", "поставь дизлайк", "убери из любимых")):
            return ("music_dislike", "дизлайк")
    # волна/любимые — через browser.py (открытие URL)
    if any(w in part for w in ("моя волна", "мою волну", "моей волны")) or _fz1(part, "моя волна"):
        return ("music:wave", "моя волна")
    if any(w in part for w in ("любимые треки", "любимые песни", "лайкнутые")) or \
       _fz1(part, "любимые треки"):
        return ("music:liked", "любимые треки")
    # поиск/включение трека — через browser.py (открывает и играет)
    if (any(w in part for w in ("включи", "поставь", "найди")) or _fz(part, ("включи", "поставь", "найди"))) and \
       any(w in part for w in ("трек", "песню", "песн", "исполнител", "артист")):
        q = part
        for w in ("включи", "поставь", "найди", "трек", "песню", "песн",
                   "исполнителя", "артиста", "в яндекс музыке", "музыку"):
            q = q.replace(w, " ")
        q = re.sub(r"\s+", " ", q).strip(" ,.")
        if q:
            return (f"music:track:{q}", f"трек: {q}")

    # Закрытие
    if any(w in part for w in _CLOSE) or _fz(part, _CLOSE):
        q = part
        for w in _CLOSE + ("процесс", "вкладку", "вкладка", "окно"):
            q = q.replace(w, " ")
        q = re.sub(r"\s+", " ", q).strip(" ,.")
        alias = {"ютуб": "youtube", "ютьюб": "youtube", "гугл": "google", "твич": "twitch",
                 "стим": "steam", "дискорд": "discord", "опера": "opera", "хром": "chrome",
                 "браузер": "opera", "телеграм": "telegram"}
        q = alias.get(q, q)
        if q:
            return (f"close_window:{q}", f"закрыть {q}")

    # «скажи …» — озвучка на устройстве
    if part.startswith("скажи "):
        phrase = part[6:].strip()
        if phrase:
            return (f"say:{phrase}", "озвучить")

    # Открытие
    if any(w in part for w in _OPEN + ("поставь", "найди")) or _fz(part, _OPEN):
        q = part
        for w in _OPEN + ("поставь", "найди", "покажи"):
            q = q.replace(w, " ")
        q = re.sub(r"\s+", " ", q).strip(" ,.")

        for yt in _YT:
            if yt in q:
                query = q.replace(yt, "")
                # Убираем предлоги и STT-артефакты вокруг «ютуб»
                for noise in (" на е ", " на ", " в ", " е ", " канал ",
                               "найди ", "найдите ", "покажи ", "открой ",
                               "включи ", "запусти "):
                    query = query.replace(noise, " ")
                query = re.sub(r"\s+", " ", query).strip(" ,.")
                if query:
                    return (f"open_youtube:{query}", f"YouTube: {query}")
                return ("open_url:https://youtube.com", "YouTube")

        for name, url in _SITES.items():
            if name in q:
                return (f"open_url:{url}", name)

        # Приложение — только если реально резолвится (иначе это не команда, а разговор)
        if q:
            target = resolve_app(q) or resolve_app(_APP_ALIAS.get(q, q))
            if target:
                return (f"open_app:{target}", f"открыть {q}")

    return None


def help_text() -> str:
    return (
        "🌸 Что я умею, Мастер:\n\n"

        "🖥 УПРАВЛЕНИЕ УСТРОЙСТВОМ:\n"
        "• открой стим / запусти ведьмак / открой ютуб котики\n"
        "• закрой стим / закрой ютуб\n"
        "• сделай громче / тише / громкость 30\n"
        "• поставь музыку / пауза / следующий трек\n"
        "• скриншот\n"
        "• скажи <текст> — произнести вслух\n"
        "Куда: «на пк» / «на ноуте». Без уточнения — на активное.\n\n"

        "🎵 МУЗЫКА:\n"
        "• поставь музыку / включи яндекс музыку\n"
        "• пауза / стоп / продолжи\n"
        "• следующий трек / предыдущий\n"
        "• лайкни трек / дизлайкни\n"
        "• что играет / мой вкус\n"
        "• моя волна / любимые треки\n"
        "• включи <исполнителя> / найди трек <название>\n\n"

        "🌐 ИНТЕРНЕТ:\n"
        "• загугли / найди в интернете <запрос>\n"
        "• открой сайт <url>\n"
        "• нарисуй <описание> — генерация картинки\n"
        "• найди картинку <запрос>\n\n"

        "📤 ОТПРАВКА В TELEGRAM:\n"
        "• пришли в телеграм <что отправить>\n"
        "• скинь в телеграм погоду / рецепт / любой запрос\n\n"

        "⏰ НАПОМИНАНИЯ:\n"
        "• напомни через 10 минут <что>\n"
        "• таймер на 5 минут\n"
        "• что напоминания — список активных\n\n"

        "🇯🇵 ПЕРЕВОД:\n"
        "• как по-японски привет\n"
        "• что значит おはよう\n"
        "• переведи <текст> на японский\n\n"

        "🎮 ИГРОВОЙ РЕЖИМ:\n"
        "• включи игровой режим / обычный режим\n\n"

        "🔍 ПОИСК В ИНТЕРНЕТЕ:\n"
        "• пришли в телеграм рецепт борща\n"
        "• найди в интернете расписание метро\n\n"

        "📋 СИСТЕМА:\n"
        "• /status — устройства\n"
        "• /health — нагрузка сервера\n"
        "• /restart — перезапуск\n"
        "• /гости — список гостей\n"
        "• /vip — список VIP\n"
        "• /users — все пользователи\n"
        "• /чистыйлист — сброс памяти\n\n"

        "💬 ЧАТЫ (мониторинг Telegram):\n"
        "• мониторь <ID> — добавить чат в наблюдение\n"
        "• убери монитор <ID> — убрать чат\n"
        "• список монитора — показать белый список\n\n"

        "🗣 ГОЛОСОМ (через агент):\n"
        "Всё то же + контекстные ответы, игры, шутки,\n"
        "погода, напоминания, перевод — по просьбе."
    )