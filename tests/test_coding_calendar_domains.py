"""Тесты развязки этапа 7: домены coding / calendar / files.

Run: python -m pytest tests/test_coding_calendar_domains.py -q

Покрывают то, что до этапа 7 было недостижимо: серверные coding.* и
calendar.list (executor=vps, реализация в capabilities/coding.py и
capabilities/calendar.py) и files.open, который свёлся к существующему
verb'у агента open_file — без правок агента.

Проверки идут через get_handler(), то есть через то же, чем пользуется
мост, и не трогают ни сеть, ни MiMo, ни git: внешние вызовы подменяются.
"""

import asyncio

import pytest

import capabilities.coding as cap_coding
import modules.calendar_module as calendar_module
import sakura_core.bridge  # noqa: F401  (регистрация таблиц доменов)
from sakura_core.executor import ExecutionContext, get_handler


def _run(coro):
    """Тот же паттерн, что в остальных тестах репозитория: asyncio.run()
    закрыл бы общий event loop и сломал легаси-хелперы других файлов."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── files.open: агентский, но нового verb'а не потребовалось ────────────


def test_files_open_uses_existing_agent_verb():
    """files.open → open_file:<query> — формат, который агент уже понимает.

    Канонического id files.open агент не знает, а verb open_file в
    agent/core/hands.py есть: execute_command разбирает строку как verb:arg,
    а file_index сам разрешает имя по всему диску.
    """
    cmd = get_handler("files.open")(ExecutionContext(param="README.md"))
    assert cmd.action == "open_file:README.md"


def test_files_open_without_query_is_an_error():
    """Пустой query — ошибка: реестр объявляет param required: ask."""
    with pytest.raises(ValueError):
        get_handler("files.open")(ExecutionContext(param=""))


# ── coding.*: серверная реализация (executor=vps) ──────────────────────


def test_coding_read_file_returns_content(tmp_path):
    """coding.read_file показывает код файла — старый путь это только обещал."""
    target = tmp_path / "sample.py"
    target.write_text("print('привет')\n", encoding="utf-8")

    text, ok = _run(get_handler("coding.read_file")(
        ExecutionContext(param=str(target))))
    assert ok is True
    assert "привет" in text


def test_coding_read_file_missing_file_is_honest():
    """Нет файла — говорим об этом (ok=False), не выдумываем содержимое."""
    text, ok = _run(get_handler("coding.read_file")(
        ExecutionContext(param="/nope/нет-такого-файла.py")))
    assert ok is False
    assert cap_coding.READ_ERROR_PREFIX in text


def test_coding_git_status_passes_project_dir(monkeypatch):
    """Регрессия переноса: run_command не принимал cwd — гиту негде было работать.

    В modules/coding.py git_status/git_commit/android_build звали
    run_command(..., cwd=PROJECT_DIR), а параметра не было: TypeError на
    каждом вызове. Проверку делаем без git — подменяем run_command.
    """
    seen = {}

    async def _fake_run(cmd, timeout=60, cwd=None):
        seen["cmd"], seen["cwd"] = cmd, cwd
        return {"ok": True, "output": " M file.py\n", "error": ""}

    monkeypatch.setattr(cap_coding, "run_command", _fake_run)

    text, ok = _run(get_handler("coding.git_status")(ExecutionContext()))
    assert ok is True
    assert seen == {"cmd": "git status --short", "cwd": cap_coding.PROJECT_DIR}
    assert "file.py" in text


def test_coding_build_without_android_project_is_honest(monkeypatch):
    """ok=False и прямое «ANDROID_PROJECT не задан» вместо падения gradle."""
    monkeypatch.setattr(cap_coding, "ANDROID_PROJECT", "")
    text, ok = _run(get_handler("coding.build")(ExecutionContext()))
    assert ok is False
    assert "ANDROID_PROJECT" in text


def test_coding_mimo_handlers_return_contract_shape(monkeypatch):
    """create_module/fix отвечают (текст, ok) — как требует контракт VPS-домена."""
    async def _ok_mimo(prompt):
        return {"ok": True, "output": f"готово: {prompt[:30]}", "error": ""}

    monkeypatch.setattr(cap_coding, "mimo_fix", _ok_mimo)
    for aid in ("coding.create_module", "coding.fix"):
        text, ok = _run(get_handler(aid)(ExecutionContext(extra={"text": "тест"})))
        assert isinstance(text, str) and text, aid
        assert ok is True, aid

    async def _fail_mimo(prompt):
        return {"ok": False, "output": "", "error": "MiMo не установлен"}

    monkeypatch.setattr(cap_coding, "mimo_fix", _fail_mimo)
    text, ok = _run(get_handler("coding.fix")(ExecutionContext(extra={"text": "тест"})))
    assert ok is False
    assert "MiMo" in text


# ── calendar.list: серверная реализация (executor=vps) ─────────────────


def test_calendar_list_renders_events(monkeypatch):
    """События из Google Calendar становятся текстом ответа."""
    monkeypatch.setattr(calendar_module, "get_upcoming_events", lambda hours_ahead=24: [
        {"summary": "Стендап", "time": "10:00", "date": "17.09", "description": ""},
    ])
    text, ok = _run(get_handler("calendar.list")(ExecutionContext()))
    assert ok is True
    assert "Стендап" in text and "10:00" in text


def test_calendar_list_separates_empty_from_unavailable(monkeypatch):
    """Пустой календарь и недоступный календарь — разные ответы.

    get_upcoming_events() глотает ошибку источника и отдаёт [], поэтому
    «событий нет» проверяется отдельно от «сервис недоступен» (правило
    честности v2: ok=False значит недоступно, а не «нет данных»).
    """
    monkeypatch.setattr(calendar_module, "get_upcoming_events", lambda hours_ahead=24: [])
    monkeypatch.setattr(calendar_module, "get_calendar_service", lambda: object())
    text, ok = _run(get_handler("calendar.list")(ExecutionContext()))
    assert ok is True
    assert "нет" in text

    def _boom():
        raise RuntimeError("token.json отсутствует")

    monkeypatch.setattr(calendar_module, "get_calendar_service", _boom)
    text, ok = _run(get_handler("calendar.list")(ExecutionContext()))
    assert ok is False
    assert "недоступ" in text
