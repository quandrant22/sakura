"""desktop.core.husk — Husk Mode: Сакура как тело для AI-агентов (Claude Code, Codex, Aider, Antigravity).

Принцип (вдохновлен capri-desktop Husk.cs):
Пока CLI/IDE агент работает в терминале, Сакура становится его оффлайн-воплощением на рабочем столе:
- Отслеживает события инструментария (PreToolCall, PostToolCall, Bash, Edit, Error).
- Голосом или системным уведомлением оповещает пользователя, когда агенту требуется подтверждение ([y/n], approval).
- Отображает текущее действие агента («Редактирую main.py...», «Запускаю тесты...»).
- Сообщает о завершении задачи или критической ошибке.

Интеграция:
1. Локальный HTTP/IPC слушатель (совместим с форматом хуков Claude Code / OpenCode / Codex).
2. Запись в husk-listener.json для автоматического обнаружения CLI-инструментами.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("sakura.husk")

_DEFAULT_PORT = 19482
_DISCOVERY_FILE = "husk-listener.json"


@dataclass
class HuskEvent:
    source: str  # "claude", "codex", "opencode", "agy", "aider"
    event_name: str  # "tool_start", "tool_end", "waiting_approval", "complete", "error"
    session_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class HuskStats:
    def __init__(self):
        self.prompts: int = 0
        self.actions: int = 0
        self.files_edited: int = 0
        self.errors: int = 0
        self.approvals: int = 0
        self.recent_actions: list[str] = []

    def record_action(self, action: str):
        self.actions += 1
        self.recent_actions.append(action[:140])
        if len(self.recent_actions) > 5:
            self.recent_actions.pop(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompts": self.prompts,
            "actions": self.actions,
            "files_edited": self.files_edited,
            "errors": self.errors,
            "approvals": self.approvals,
            "recent": list(self.recent_actions),
        }


def format_action_caption(tool: str, tool_input: dict[str, Any]) -> str:
    """Форматирует краткую реплику/подпись для действия агента в духе Сакуры."""
    tool_lower = (tool or "").lower()
    
    # Редактирование / запись файлов
    if any(k in tool_lower for k in ("edit", "write", "patch", "notebookedit")):
        paths = []
        for k in ("file_path", "path", "filename", "target_file"):
            if k in tool_input and isinstance(tool_input[k], str):
                paths.append(Path(tool_input[k]).name)
        if "file_paths" in tool_input and isinstance(tool_input["file_paths"], list):
            paths.extend(Path(p).name for p in tool_input["file_paths"] if isinstance(p, str))
        if paths:
            unique_paths = list(dict.fromkeys(paths))
            if len(unique_paths) == 1:
                return f"Редактирую {unique_paths[0]}..."
            return f"Редактирую {len(unique_paths)} файлов ({', '.join(unique_paths[:2])})..."
        return f"Редактирую файл ({tool})..."

    # Bash / команды консоли
    if any(k in tool_lower for k in ("bash", "run_command", "terminal", "exec", "sh")):
        cmd = str(tool_input.get("command") or tool_input.get("CommandLine") or "").strip()
        cmd_clean = re.sub(r"\s+", " ", cmd)
        if len(cmd_clean) > 40:
            cmd_clean = cmd_clean[:37] + "..."
        return f"Выполняю `{cmd_clean}`" if cmd_clean else "Выполняю команду в терминале..."

    # Чтение файлов / поиск
    if any(k in tool_lower for k in ("read", "view", "cat")):
        p = tool_input.get("file_path") or tool_input.get("Path") or ""
        leaf = Path(str(p)).name if p else ""
        return f"Читаю {leaf}" if leaf else "Читаю файл..."

    if any(k in tool_lower for k in ("grep", "glob", "search", "find")):
        pattern = tool_input.get("pattern") or tool_input.get("query") or ""
        return f"Ищу «{pattern}»..." if pattern else "Ищу в кодовой базе..."

    return f"Запускаю {tool}..."


class HuskManager:
    """Управляет приёмом событий от AI-агентов и оповещением пользователя через Сакуру."""

    def __init__(
        self,
        on_say: Optional[Callable[[str], None]] = None,
        on_notify: Optional[Callable[[str, str], None]] = None,
        storage_dir: Optional[str] = None,
        port: int = _DEFAULT_PORT,
    ):
        self.on_say = on_say or (lambda text: log.info("Husk Say: %s", text))
        self.on_notify = on_notify or (lambda title, text: log.info("Husk Notify [%s]: %s", title, text))
        self.port = port
        self.storage_dir = Path(storage_dir or os.path.expandvars(r"%LOCALAPPDATA%\Sakura\husk"))
        self.stats = HuskStats()
        self.enabled = True
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_caption_time = 0.0

    def start(self):
        """Запуск локального HTTP-сервера для приёма хуков."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self._write_discovery()
            
            manager = self

            class _HookHandler(BaseHTTPRequestHandler):
                def do_POST(self):
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length).decode("utf-8", errors="replace")
                    try:
                        data = json.loads(body) if body else {}
                        manager.handle_hook_payload(data)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"ok"}')
                    except Exception as e:
                        log.warning("Husk parse error: %s", e)
                        self.send_response(400)
                        self.end_headers()

                def do_GET(self):
                    if self.path == "/stats":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps(manager.stats.to_dict()).encode("utf-8"))
                        return
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Sakura Husk Bridge Active")

                def log_message(self, format, *args):
                    pass  # Тихо в консоли

            self._server = HTTPServer(("127.0.0.1", self.port), _HookHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="SakuraHuskServer")
            self._thread.start()
            log.info("Husk mode bridge started on 127.0.0.1:%d", self.port)
        except Exception as exc:
            log.error("Failed to start Husk server: %s", exc)

    def stop(self):
        """Остановка сервера и удаление файла дискавери."""
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        self._remove_discovery()

    def _write_discovery(self):
        """Записывает файл husk-listener.json для автоматического подключения CLI."""
        info = {
            "port": self.port,
            "url": f"http://127.0.0.1:{self.port}/hook",
            "version": 1,
            "pid": os.getpid(),
        }
        for target_dir in [
            self.storage_dir,
            Path(os.path.expanduser("~")),
        ]:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / _DISCOVERY_FILE).write_text(json.dumps(info, indent=2), encoding="utf-8")
            except Exception as e:
                log.debug("Could not write discovery to %s: %s", target_dir, e)

    def _remove_discovery(self):
        for target_dir in [self.storage_dir, Path(os.path.expanduser("~"))]:
            try:
                p = target_dir / _DISCOVERY_FILE
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    def handle_hook_payload(self, data: dict[str, Any]):
        """Обрабатывает входящее событие от хука кодинг-агента."""
        if not self.enabled:
            return

        event_name = data.get("hook_event_name") or data.get("event") or "unknown"
        source = data.get("source") or data.get("agent_type") or "claude"
        tool_name = data.get("tool_name") or ""
        tool_input = data.get("tool_input") or {}
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except Exception:
                tool_input = {"text": tool_input}

        error = data.get("error")
        summary = data.get("message") or data.get("last_assistant_message") or ""

        # События ожидания разрешения от пользователя
        if event_name in ("permission_request", "approval_required", "waiting_approval") or data.get("permission_mode") == "ask":
            self.stats.approvals += 1
            cmd_preview = format_action_caption(tool_name, tool_input)
            self.on_say(f"Мастер, агент просит подтвердить действие: {cmd_preview}")
            self.on_notify("Сакура: Требуется подтверждение", f"Агент ожидает апрува: {tool_name}")
            return

        # Запуск инструмента
        if event_name in ("PreToolCall", "tool_start"):
            caption = format_action_caption(tool_name, tool_input)
            with self._lock:
                self.stats.record_action(caption)
                if "edit" in tool_name.lower() or "write" in tool_name.lower():
                    self.stats.files_edited += 1

            # Не спамим репликами чаще чем раз в 4 секунды для пачки мелких чтений
            now = time.time()
            if now - self._last_caption_time >= 3.5:
                self._last_caption_time = now
                self.on_notify("Сакура Кодинг", caption)

        # Ошибки
        elif error or event_name in ("error", "ToolError"):
            self.stats.errors += 1
            err_text = str(error or "Произошла ошибка при выполнении шага")
            if len(err_text) > 80:
                err_text = err_text[:77] + "..."
            self.on_notify("Сакура: Ошибка агента", err_text)

        # Завершение задачи / сессии
        elif event_name in ("SessionEnd", "task_complete", "complete"):
            self.on_say("Агент завершил задачу!")
            self.on_notify("Сакура", f"Задача завершена: {summary[:100]}" if summary else "Агент завершил задачу.")
