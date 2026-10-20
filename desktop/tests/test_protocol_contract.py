"""Контракт протокола: запросы клиента ↔ CLIENT_REQUESTS ↔ V2_REQUESTS сервера.

1. Все типы запросов, которые шлёт клиент (ядро — link.request, окно — client.server и Memory),
   перечислены в desktop/core/protocol.py (CLIENT_REQUESTS или CLIENT_OTHER_REQUESTS), и наоборот.
2. Каждый тип из CLIENT_REQUESTS есть в V2_REQUESTS сервера (sakura_core/proto_v2.py из ветки
   origin/server/presence-memory; без неё — файл рядом в репозитории; нет ни того, ни другого — skip).
3. Мок-сервер знает ровно те же запросы, что сервер.
"""
import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

from desktop.core.protocol import CLIENT_OTHER_REQUESTS, CLIENT_REQUESTS
from desktop.tools import mock_server

DESKTOP = Path(__file__).resolve().parents[1]
REPO = DESKTOP.parent
SERVER_REF = "origin/server/presence-memory"
SERVER_FILE = "sakura_core/proto_v2.py"

# Окно: client.server<…>({ type: "x" …}) и request({ type: "x" …}) / msg = { type: "x" … } в Memory.tsx.
TS_CALL = re.compile(r"\.server\b[^(]*\(\s*\{\s*type:\s*\"(\w+)\"")
TS_LITERAL = re.compile(r"\btype:\s*\"(\w+)\"")
# Ядро: link.request({"type": "x" …}).
PY_CALL = re.compile(r"\.request\(\s*\{\s*\"type\":\s*\"(\w+)\"")
# Похожие на запрос имена: литерал с таким префиксом в коде окна обязан быть в списке.
REQUEST_LIKE = re.compile(r"^(chat_|history_|memory_|profile_|scenario|secure_|devices_request|status_request"
                          r"|vision_request)")
# Не запросы: ответы и события сервера, которые окно разбирает или показывает.
TS_SKIP = {"api/demo.ts", "api/types.ts"}
NOT_REQUESTS = {"chat_message", "scenario_event", "scenario_run_started", "scenario_preview", "scenarios"}


def _ts_sources():
    for path in (DESKTOP / "ui" / "src").rglob("*.ts*"):
        rel = path.relative_to(DESKTOP / "ui" / "src").as_posix()
        if ".test." in rel or rel in TS_SKIP:
            continue
        yield rel, path.read_text(encoding="utf-8")


def _py_sources():
    for path in (DESKTOP / "core").rglob("*.py"):
        yield path.relative_to(DESKTOP).as_posix(), path.read_text(encoding="utf-8")


def client_requests() -> dict[str, set[str]]:
    """Тип запроса → файлы, где клиент его шлёт."""
    found: dict[str, set[str]] = {}
    for rel, text in _ts_sources():
        names = set(TS_CALL.findall(text))
        names |= {n for n in TS_LITERAL.findall(text) if REQUEST_LIKE.match(n) and n not in NOT_REQUESTS}
        for n in names:
            found.setdefault(n, set()).add(f"ui/src/{rel}")
    for rel, text in _py_sources():
        for n in PY_CALL.findall(text):
            found.setdefault(n, set()).add(rel)
    return found


def _server_source() -> tuple[str | None, str]:
    env = os.getenv("SAKURA_SERVER_PROTO_V2")
    if env and Path(env).is_file():
        return Path(env).read_text(encoding="utf-8"), env
    try:
        out = subprocess.run(["git", "-C", str(REPO), "show", f"{SERVER_REF}:{SERVER_FILE}"],
                             capture_output=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("utf-8"), f"{SERVER_REF}:{SERVER_FILE}"
    except (OSError, subprocess.SubprocessError):
        pass
    local = REPO / SERVER_FILE
    if local.is_file():
        return local.read_text(encoding="utf-8"), str(local)
    return None, f"нет {SERVER_REF}:{SERVER_FILE} и {local}"


def server_v2_requests() -> frozenset[str]:
    """V2_REQUESTS сервера — разбором исходника (импорт тянет конфиг и состояние сервера)."""
    src, where = _server_source()
    if src is None:
        pytest.skip(f"исходник сервера недоступен ({where}) — сверка с V2_REQUESTS пропущена")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "V2_REQUESTS" for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call):  # frozenset({...})
                value = value.args[0]
            return frozenset(ast.literal_eval(value))
    pytest.fail(f"V2_REQUESTS не найден в {where}")


def test_client_code_sends_only_listed_requests():
    used = client_requests()
    listed = CLIENT_REQUESTS | CLIENT_OTHER_REQUESTS
    extra = {k: sorted(v) for k, v in used.items() if k not in listed}
    assert not extra, f"запросы вне desktop/core/protocol.py CLIENT_REQUESTS: {extra}"


def test_every_listed_request_is_used():
    unused = (CLIENT_REQUESTS | CLIENT_OTHER_REQUESTS) - set(client_requests())
    assert not unused, f"в CLIENT_REQUESTS лишнее (клиент не шлёт): {sorted(unused)}"


def test_lists_do_not_overlap():
    assert not CLIENT_REQUESTS & CLIENT_OTHER_REQUESTS


def test_client_requests_known_to_server():
    server = server_v2_requests()
    missing = CLIENT_REQUESTS - server
    assert not missing, f"сервер не знает запросы клиента: {sorted(missing)}"
    # Обработчики вне диспетчера v2 — не в V2_REQUESTS (иначе им место в CLIENT_REQUESTS).
    assert not CLIENT_OTHER_REQUESTS & server


def test_mock_server_matches_server():
    assert mock_server.V2_REQUESTS == server_v2_requests()


def test_scanner_sees_known_call_sites():
    """Проверка самого сканера: известные места вызова находятся."""
    used = client_requests()
    assert "ui/src/store.ts" in used["chat_search"]
    assert "ui/src/screens/Memory.tsx" in used["memory_delete"]
    assert "core/service.py" in used["secure_devices"]
    assert "core/service.py" in used["vision_request"]
