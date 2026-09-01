"""
tools/test_parallel.py — диагностика Parallel Search MCP (https://search.parallel.ai/mcp).

Показывает: инструменты сервера (tools/list) с их схемами аргументов и
сырой ответ одного web_search. Запуск:

    ./venv/bin/python3 tools/test_parallel.py [запрос]

Только анонимный доступ (без OAuth/Bearer), как решил Мастер.
"""
import asyncio
import json
import sys

MCP_URL = "https://search.parallel.ai/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
TIMEOUT = 20.0


def _parse_body(content_type: str, body: str) -> list[dict]:
    """JSON-RPC ответ(ы): одиночный JSON ИЛИ SSE-поток (data: строки)."""
    ct = (content_type or "").lower()
    msgs: list[dict] = []
    if "text/event-stream" in ct:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    try:
                        msgs.append(json.loads(chunk))
                    except json.JSONDecodeError:
                        pass
    else:
        try:
            msgs.append(json.loads(body))
        except json.JSONDecodeError:
            pass
    return msgs


async def _post(httpx, sid: str | None, payload: dict):
    """POST одного JSON-RPC сообщения. Возвращает (status, headers, msgs, raw)."""
    headers = dict(HEADERS)
    if sid:
        headers["Mcp-Session-Id"] = sid
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(MCP_URL, headers=headers, content=json.dumps(payload))
        raw = r.text
        msgs = _parse_body(r.headers.get("content-type", ""), raw)
        return r.status_code, r.headers, msgs, raw


async def main(query: str) -> None:
    import httpx

    # 1. initialize — установка сессии
    status, headers, msgs, raw = await _post(httpx, None, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "sakura", "version": "1.0"},
        },
    })
    print(f"=== initialize: HTTP {status}")
    print(raw[:600])
    init = next((m for m in msgs if m.get("id") == 1), None)
    if init is None or "result" not in init:
        print("!! initialize не дал result — дальше идти бессмысленно")
        return
    sid = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
    print(f"=== Mcp-Session-Id: {sid or '(не выдан — stateless, это нормально)'}")

    # 2. notifications/initialized
    status, _, _, raw = await _post(httpx, sid, {
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    print(f"=== notifications/initialized: HTTP {status} body={raw[:120]!r}")

    # 3. tools/list — ТОЧНЫЕ имена инструментов и схем аргументов
    status, _, msgs, _ = await _post(httpx, sid, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list",
    })
    listed = next((m for m in msgs if m.get("id") == 2), None)
    print(f"=== tools/list: HTTP {status}")
    if not listed or "result" not in listed:
        print(raw[:600])
        return
    for t in listed["result"].get("tools", []):
        print(f"\n-- tool: {t.get('name')}")
        desc = (t.get("description") or "").strip().replace("\n", " ")
        print(f"   desc: {desc[:160]}")
        print(f"   inputSchema: {json.dumps(t.get('inputSchema', {}), ensure_ascii=False)}")

    # 4. tools/call web_search — сырой ответ
    # Требования схемы (проверено tools/list): objective И search_queries
    # (массив 1-3 ключевых запросов по 3-6 слов) — ОБА обязательны.
    keywords = " ".join(w.strip(",.!?«»\"'") for w in query.split()[:6])
    status, _, msgs, raw = await _post(httpx, sid, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "web_search",
                   "arguments": {"objective": query,
                                 "search_queries": [keywords]}},
    })
    print(f"\n=== tools/call web_search({query!r}): HTTP {status}")
    print(f"    arguments: {json.dumps({'objective': query, 'search_queries': [keywords]}, ensure_ascii=False)}")
    called = next((m for m in msgs if m.get("id") == 3), None)
    if called is None:
        print("RAW:", raw[:1500])
        return
    if "error" in called:
        print("JSON-RPC ERROR:", json.dumps(called["error"], ensure_ascii=False)[:800])
        return
    print("RAW result:", json.dumps(called.get("result", {}), ensure_ascii=False)[:6000])


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or "кто сейчас президент Франции"
    asyncio.run(main(q))
