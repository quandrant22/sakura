"""desktop.core.results — единый контракт результата команды.

{ok, status, detail}:
  status = done        — действие выполнено (только тогда сервер говорит «Готово»);
           noop        — делать нечего (уже так, нет активного плеера);
           failed      — пытались, не вышло;
           unsupported — команда неизвестна или недоступна без чего-то (расширения, токена).
  ok = (status == "done") — никогда не true при неудаче.

Старые исполнители (hands, browser, music) возвращают строку или dict с «ok»; classify()
переводит их в контракт по явным признакам неудачи в тексте.
"""
DONE, NOOP, FAILED, UNSUPPORTED = "done", "noop", "failed", "unsupported"
STATUSES = (DONE, NOOP, FAILED, UNSUPPORTED)

# Признаки в тексте старых исполнителей (нижний регистр, подстрока).
_UNSUPPORTED = ("неизвестная", "не поддерживается", "не подключено", "нужен токен", "недоступн",
                "не загружено", "не реализован")
_NOOP = ("нет активного плеера", "ничего не играет", "неизвестно что играет")
_FAILED = ("не найден", "не нашла", "не удалось", "не выполнил", "нет доступа", "ошибка", "error", "не открыта",
           "app_not_found:", "file_not_found:", "не указан", "пустое", "пуста", "плейлист пуст",
           "таймаут", "не приняла")  # не «пуст»: он есть внутри «запустила»


def result(status: str, detail: str, **extra) -> dict:
    if status not in STATUSES:
        raise ValueError(f"неизвестный статус: {status}")
    return {"ok": status == DONE, "status": status, "detail": detail, **extra}


def done(detail: str, **extra) -> dict:
    return result(DONE, detail, **extra)


def failed(detail: str, **extra) -> dict:
    return result(FAILED, detail, **extra)


def noop(detail: str, **extra) -> dict:
    return result(NOOP, detail, **extra)


def unsupported(detail: str, **extra) -> dict:
    return result(UNSUPPORTED, detail, **extra)


def classify_text(text: str | None) -> str:
    """Статус по тексту старого исполнителя. Пустой текст — неудача, а не успех."""
    t = (text or "").strip().lower()
    if not t:
        return FAILED
    for marks, status in ((_NOOP, NOOP), (_UNSUPPORTED, UNSUPPORTED), (_FAILED, FAILED)):
        if any(m in t for m in marks):
            return status
    return DONE


def from_legacy(value, detail_key: str = "detail") -> dict:
    """Строка или dict старого исполнителя → контракт.

    dict с явным ok=False никогда не становится done; ok=True проверяется ещё и по тексту.
    """
    if isinstance(value, dict):
        if value.get("status") in STATUSES:
            return result(value["status"], str(value.get("detail", "")))
        text = str(value.get(detail_key) or value.get("result") or value.get("error") or "")
        if value.get("ok") is False or value.get("error"):
            status = classify_text(text)
            return result(FAILED if status == DONE else status, text or "не удалось")
        return result(classify_text(text) if text else DONE, text or "выполнено")
    text = "" if value is None else str(value)
    return result(classify_text(text), text or "пустой результат")
