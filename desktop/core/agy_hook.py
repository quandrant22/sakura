#!/usr/bin/env python3
"""Хук жизненного цикла Antigravity для Сакуры (Husk Mode).

Вызывается Antigravity через .agents/hooks.json на событиях PreToolUse, PostToolUse и Stop.
Передаёт события на локальный порт Сакуры (127.0.0.1:19482) для голосовых оповещений
и отслеживания промежуточного прогресса.
"""

import json
import sys
import urllib.request

HUSK_URL = "http://127.0.0.1:19482/hook"


def main():
    event_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    data = {}
    if raw_input.strip():
        try:
            data = json.loads(raw_input)
        except Exception:
            pass

    # Формируем событие для Husk
    payload = {"source": "agy"}

    if event_type == "pre_tool":
        tool_call = data.get("toolCall") or {}
        tool_name = tool_call.get("name") or "tool"
        tool_args = tool_call.get("args") or {}
        payload.update({
            "hook_event_name": "PreToolCall",
            "tool_name": tool_name,
            "tool_input": tool_args,
        })
    elif event_type == "post_tool":
        tool_call = data.get("toolCall") or {}
        tool_name = tool_call.get("name") or "tool"
        payload.update({
            "hook_event_name": "tool_end",
            "tool_name": tool_name,
        })
    elif event_type == "stop":
        reason = data.get("terminationReason") or "NO_TOOL_CALL"
        payload.update({
            "hook_event_name": "complete",
            "message": f"Задача в Антигравити завершена ({reason})",
        })

    # Отправляем в Сакуру тихо (без блокировки Antigravity при ошибке соединения)
    try:
        req = urllib.request.Request(
            HUSK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.0):
            pass
    except Exception:
        pass

    # Ответ Antigravity по контракту stdout
    if event_type == "pre_tool":
        print(json.dumps({"decision": "proceed"}))
    else:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
