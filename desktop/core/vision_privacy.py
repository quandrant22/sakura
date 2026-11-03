"""desktop.core.vision_privacy — окна, на которые Сакура не смотрит.

Проверяется ДО снятия экрана (docs/VISION.md): приватное окно на переднем
плане → ответ skipped/private_window, кадр не создаётся вовсе.

Приватно:
  - менеджеры паролей (по имени процесса);
  - окна инкогнито/InPrivate, банки, страницы входа (по заголовку);
  - любой пункт пользовательского списка (часть заголовка или имени процесса);
  - фокус в поле пароля (UI Automation), если проверка доступна.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("sakura.vision")

PRIVATE_PROCESSES = frozenset({
    "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe",
    "dashlane.exe", "enpass.exe", "nordpass.exe", "roboform.exe", "proton pass.exe",
    "keeper.exe", "passwordsafe.exe",
})

_TITLE = re.compile(
    r"(?<!\w)("
    r"inprivate|incognito|инкогнито|приватн\w* (?:окно|просмотр|режим)|private browsing|"
    r"keepass\w*|1password|bitwarden|lastpass|"
    r"сбербанк|сбер ?онлайн|сбербизнес|т-банк|тинькофф|альфа-?(?:банк|онлайн|клик)|втб|газпромбанк|"
    r"райффайзен|открытие онлайн|почта банк|озон банк|ozon bank|банк[\s-]?онлайн|интернет-банк|"
    r"госуслуги|nalog\.ru|личный кабинет налогоплательщика|"
    r"paypal|online banking|"
    r"парол\w*|password|вход в аккаунт|sign in|log ?in"
    r")(?!\w)",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def is_private(title: str, process: str, extra: list[str] | tuple[str, ...] = ()) -> bool:
    """Окно приватное по заголовку, процессу или пользовательскому списку."""
    t, p = _norm(title), _norm(process)
    if p in PRIVATE_PROCESSES:
        return True
    if _TITLE.search(t):
        return True
    for item in extra or ():
        needle = _norm(str(item))
        if needle and (needle in t or needle == p or needle in p):
            return True
    return False


def password_focused() -> bool:
    """Фокус в поле пароля. Нет UI Automation (другая ОС, сбой) — False:
    по одной этой проверке кадр не запрещаем, остальные правила работают."""
    try:
        from desktop.core.platform import uia
        return bool(uia.focused_is_password())
    except Exception as e:
        log.debug("[vision] проверка поля пароля недоступна: %s", type(e).__name__)
        return False
