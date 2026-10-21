"""desktop.core.securechannel.loader — загрузка защищённого канала, не блокирующая цикл событий.

Модули канала тянут cryptography (X25519, ChaCha20-Poly1305): первый импорт — сотни миллисекунд, а без
пакета — исключение. Поэтому ядро грузит их в потоке (asyncio.to_thread) — заранее, в фоне при старте, и
перед каждой командой «Безопасности», если ещё не загружены. Нет пакета — SecureUnavailable с понятным
текстом, команда отвечает ошибкой, цикл не ждёт.
"""
import asyncio
import importlib
import logging

log = logging.getLogger("sakura.secure")

MODULES = ("desktop.core.securechannel.noise", "desktop.core.securechannel.keys",
           "desktop.core.securechannel.pairing", "desktop.core.securechannel.client")
MISSING_TEXT = ("Не установлен пакет cryptography — защищённый канал недоступен. "
                "Установите зависимости: pip install -r desktop/requirements.txt")


class SecureUnavailable(Exception):
    pass


_state: dict = {"ok": None, "error": None}


def load_sync() -> None:
    """Импорт модулей канала (в потоке). Результат запоминается: второй вызов ничего не делает."""
    if _state["ok"] is not None:
        return
    try:
        for name in MODULES:
            importlib.import_module(name)
    except ImportError as e:
        _state.update(ok=False, error=MISSING_TEXT if "cryptography" in str(e) else f"защищённый канал недоступен: {e}")
        log.warning("[secure] %s", _state["error"])
        return
    _state.update(ok=True, error=None)


async def load() -> None:
    """Загрузить в потоке; канал недоступен — SecureUnavailable (без ожидания в цикле событий)."""
    if _state["ok"] is None:
        await asyncio.to_thread(load_sync)
    if not _state["ok"]:
        raise SecureUnavailable(_state["error"] or MISSING_TEXT)


def preload() -> "asyncio.Future":
    """Фоновая загрузка при старте ядра: к открытию «Безопасности» модули уже в памяти."""
    async def run():
        try:
            await load()
        except SecureUnavailable:
            pass
    return asyncio.ensure_future(run())


def reset() -> None:
    """Для тестов: забыть результат загрузки."""
    _state.update(ok=None, error=None)
