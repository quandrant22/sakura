"""desktop.core.control — управление компьютером (п. 2.3–2.4): окна, питание, процессы, буфер
обмена, экран и звук, сеть, клавиатура, файлы.

execute(action, arg, confirmed) → {ok, status, detail} (desktop.core.results).
Безопасность: действия с confirm выполняются только с confirmed=True (подтверждение спрашивает
сервер); не больше RATE_PER_S действий в секунду; ui.* и keys.* не трогают окна из чёрного
списка (WINDOW_BLOCKLIST) и не печатают в поля паролей; журнал — только id и статус, без
текстов ввода и изображений. Платформенные вызовы — только через desktop.core.platform.
"""
from desktop.core.control.registry import ACTIONS, execute  # noqa: F401
