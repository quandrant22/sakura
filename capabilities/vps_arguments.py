"""Extract VPS arguments after the registry has selected a canonical action."""
import re


def arguments(action: str, text: str, param: str = "") -> tuple[str, str]:
    """Return the voice_info action and its argument, preserving source text."""
    low = text.lower().strip().rstrip(".!?,")
    if param:
        return action, param
    if action == "steam.achievements":
        game = re.search(r"(?:ачивки|достижения|достижений)\s+(?:в|по)\s+(?:игре\s+)?(.+?)(?:\s+за\s+.+)?$", low)
        if game and game[1] not in ("игре", "игру"):
            return "steam.achievements:game", game[1]
    if action in ("steam.achievements", "music_stats.recent", "music_stats.top"):
        from modules.voice_info import _default_period_word
        # Match whole words: «позавчера» is not «вчера».
        period = re.search(r"(?<!\w)(вчера|сегодня|месяц|30 дней|всё время|все время|всего|за день)(?!\w)", low)
        return action, _default_period_word(period[1] if period else "")
    patterns = {
        "steam.playtime": r"(?:наиграл|часов|наиграно)\s+(?:в\s+)?(.+)$",
        "steam.progress": r"(?:в|по)\s+(?:игре\s+)?(.+)$",
        "task.add": r"(?:добавь|создай|запиши)\s+задачу\s+(.+)$",
        "task.done": r"(?:задач[ауи]|задача)\s*(\d+)",
        "memory.forget": r"(?:забудь (?:про|что)|(?:удали|сотри) из памяти|не помни про)\s+(.+)$",
    }
    pattern = patterns.get(action)
    match = re.search(pattern, low) if pattern else None
    return action, match[1] if match else ""
