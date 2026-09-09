"""
core/dep_check.py — проверка критичных пакетов при старте агента.

Зачем: многие модули оборачивают импорты в try/except ImportError и
МОЛЧА деградируют (например, yamusic_app без winsdk → «Яндекс Музыка
не отвечает»). Чтобы таких сюрпризов не было, при старте агента
я проверяю критичные пакеты и пишу ЯВНОЕ предупреждение в лог:

    [agent] winsdk не установлен — управление музыкой недоступно

Вызывается из core/agent.Agent.__init__ (обе точки входа — sakura.py
и launch.py — конструируют Agent). Повторные вызовы — no-op.
"""

import importlib
import logging

log = logging.getLogger("sakura.agent")

# (import-имя, pip-имя, что отвалится без пакета)
_CRITICAL_PACKAGES = [
    ("websockets",     "websockets",     "связь с VPS-сервером недоступна"),
    ("winsdk",         "winsdk",         "управление музыкой недоступно"),
    ("yandex_music",   "yandex-music",   "API Яндекс Музыки недоступен"),
    ("sounddevice",    "sounddevice",    "захват/воспроизведение звука недоступны"),
    ("numpy",          "numpy",          "обработка аудио недоступна"),
    ("vosk",           "vosk",           "распознавание речи (STT) недоступно"),
    ("torch",          "torch",          "VAD (silero) недоступен"),
    ("silero_vad",     "silero-vad",     "VAD (silero) недоступен"),
    ("pyaudiowpatch",  "PyAudioWPatch",  "WASAPI loopback (музыка/звук системы) недоступен"),
    ("PyQt6",          "PyQt6",          "графический интерфейс недоступен"),
    ("pyautogui",      "pyautogui",      "эмуляция ввода недоступна"),
    ("pyperclip",      "pyperclip",      "буфер обмена недоступен"),
    ("win32gui",       "pywin32",        "управление окнами/хоткеи недоступны"),
    ("PIL",            "pillow",         "скриншоты/изображения недоступны"),
    ("pycaw",          "pycaw",          "управление громкостью недоступно"),
    ("comtypes",       "comtypes",       "управление громкостью недоступно"),
    ("bleak",          "bleak",          "Bluetooth-устройства недоступны"),
    ("psutil",         "psutil",         "мониторинг системы недоступен"),
    ("httpx",          "httpx",          "HTTP-запросы (поиск/парсинг) недоступны"),
]

_checked = False


def check_critical_packages(force: bool = False) -> list:
    """Проверяет критичные пакеты, логирует WARNING для отсутствующих.

    Возвращает список отсутствующих import-имён. Вызывается один раз
    за жизнь процесса (повторные вызовы — no-op, кроме force=True).
    """
    global _checked
    if _checked and not force:
        return []
    _checked = True

    missing = []
    for module_name, pip_name, impact in _CRITICAL_PACKAGES:
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)
            # ВАЖНО: явное предупреждение, а не молчаливый except ImportError
            log.warning(
                "[agent] %s не установлен — %s (pip install %s)",
                module_name, impact, pip_name,
            )
    return missing
