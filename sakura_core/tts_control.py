"""TTS stop detection — shared between TG and voice adapters.

Matches "стоп", "хватит", etc. and returns True if TTS was stopped.
The adapter handles I/O (send confirmation to user).
"""

import re

_STOP_RE = re.compile(
    r"(?<!\w)(?:стоп|хватит|достаточно|останови\s+чтение|"
    r"перестань\s+читать|хватит\s+читать)\w*",
    re.IGNORECASE,
)

_STOP_EXACT = frozenset({
    "стоп", "хватит", "достаточно",
    "останови чтение", "перестань читать", "хватит читать",
})


# «стоп задача», «стоп браузер», «хватит в браузере» — команды остановки
# задачи агента браузера (browser.stop), а не чтения: их ловит реестр.
_TASK_STOP_RE = re.compile(r"(?<!\w)(?:задач\w*|браузер\w*)", re.IGNORECASE)


def is_tts_stop(text: str) -> bool:
    """Return True if text is a TTS-stop phrase."""
    t = text.lower().strip().rstrip(".!?,")
    if t in _STOP_EXACT:
        return True
    if _TASK_STOP_RE.search(t):
        return False
    return bool(_STOP_RE.search(text.lower()))
