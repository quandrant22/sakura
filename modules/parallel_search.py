"""
modules/parallel_search.py — веб-поиск Сакуры через Parallel Search MCP.

Сервер: https://search.parallel.ai/mcp (Streamable HTTP, JSON-RPC 2.0).
Минимальный клиент поверх httpx — JSON-RPC вручную, без тяжёлого MCP SDK.
Анонимный доступ без OAuth/Bearer — решение Мастера (бесплатно, без аккаунта).

Контракт: parallel_search(query) -> (текст_выдержек, источники, ok).
Выдержки уже сжаты под запрос — не сырые страницы, как у прежнего фолбэка.

Формат ответа web_search (проверено tools/list + живым прогоном 2026-09):
  result.structuredContent = {"search_id", "results", "warnings", "session_id"}
  тот же JSON продублирован в content[0].text;
  results[i] = {"url", "title", "publish_date", "excerpts": [str, ...]}.
Схема web_search требует ОБА поля: objective И search_queries (массив
ключевых запросов 3-6 слов) — поэтому keywords синтезируются из запроса.
"""

import asyncio
import json
import logging
import re
import uuid

import httpx

log = logging.getLogger(__name__)

MCP_URL = "https://search.parallel.ai/mcp"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_TIMEOUT = 20.0
_PROTOCOL_VERSION = "2025-03-26"

# Стабильный идентификатор клиента на жизнь процесса: Parallel просит
# переиспользовать одно значение session_id на все вызовы (free-tier rate
# limiting и корреляция в их логах).
_SESSION_ID = uuid.uuid4().hex


def _parse_body(content_type: str, body: str) -> list[dict]:
    """JSON-RPC-ответ(ы) из тела: одиночный JSON ИЛИ SSE-поток (data: строки)."""
    msgs: list[dict] = []
    if "text/event-stream" in (content_type or "").lower():
        for line in (body or "").splitlines():
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
        except (json.JSONDecodeError, TypeError):
            pass
    return msgs


async def _rpc(client: "httpx.AsyncClient", sid: str | None, payload: dict):
    """POST одного JSON-RPC сообщения. → (status, headers, messages)."""
    headers = dict(_HEADERS)
    if sid:
        headers["Mcp-Session-Id"] = sid
    r = await client.post(MCP_URL, headers=headers, content=json.dumps(payload))
    msgs = _parse_body(r.headers.get("content-type", ""), r.text)
    return r.status_code, r.headers, msgs


def _keywords(query: str) -> list[str]:
    """Ключевой запрос 3-6 слов из фразы Мастера (схема требует search_queries)."""
    words = []
    for w in (query or "").split():
        w = w.strip(",.!?;:«»\"'()…")
        if w:
            words.append(w)
        if len(words) >= 6:
            break
    return [" ".join(words)] if words else [query.strip()[:50] or "новости"]


# Резерв важен: сырые первые слова теряют названия игр и навыков, поэтому
# основной путь — build_search_queries() через MAIN_MODEL (см. ниже).

_QUERY_PROMPT = (
    "Составь 1-3 поисковых запроса для веб-поиска по фразе Мастера. Правила:\n"
    "1. Сохраняй имена собственные, названия игр и точные названия предметов, "
    "навыков, трейтов — в кавычках, если они были в кавычках во фразе.\n"
    "2. Сохраняй тип предмета из фразы (трейт, навык, оружие, босс, материал) — "
    "это слово сужает поиск до нужного раздела гайдов.\n"
    "3. Русскую транслитерацию заменяй на оригинал: «ремнант фром зе эшс» → "
    "Remnant: From the Ashes, «палворлд» → Palworld, «ельден ринг» → Elden Ring.\n"
    "4. Добавь уточняющий контекст, если он ясен из вопроса (игра, платформа, "
    "год, «как получить», «патчноут»). Но не добавляй того, чего во фразе нет.\n"
    "5. Каждый запрос — 3-7 ключевых слов, без воды и пояснений.\n"
    "Ответь ТОЛЬКО JSON-массивом строк, без текста вокруг.\n\n"
    "Фраза Мастера: "
)


def _strip_wrap_quotes(q: str) -> str:
    """Снимает только полностью обрамляющие кавычки-пару (мусор модели).

    Внутренние кавычки названий («трейт „Мастер…"») сохраняются.
    """
    for a, b in (("«", "»"), ('"', '"'), ("“", "”")):
        if len(q) >= 2 and q.startswith(a) and q.endswith(b):
            return q[1:-1].strip()
    return q


def _parse_model_queries(text: str, limit: int = 3) -> list[str]:
    """Ответ модели → список запросов (JSON-массив строк, ≤limit, без мусора)."""
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[str] = []
    for item in arr if isinstance(arr, list) else []:
        if isinstance(item, str):
            q = _strip_wrap_quotes(item.strip())
            if q and len(q) <= 200:
                out.append(q)
        if len(out) >= limit:
            break
    return out


def _fallback_query(query: str) -> str:
    """Сырая фраза без глагола поиска — подстраховка, если модель промахнулась."""
    q = re.sub(
        r"^(найдите|поищите|загуглите|погуглите|найди|поищи|загугли|погугли|поиши)\s*[::,-]?\s*",
        "", (query or "").strip(), flags=re.I)
    return _keywords(q)[0]


async def _model_queries(query: str) -> list[str]:
    """Один дешёвый вызов MAIN_MODEL: фраза Мастера → 1-3 поисковых запроса.

    Сбой/пустой ответ → [] (вызывающая сторона уйдёт в резерв _keywords()).
    Все аргументы generate_content — именованные (SDK keyword-only).
    """
    from config import MAIN_MODEL, get_active_key, mark_key_used
    key = get_active_key()
    if not key:
        return []
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    cfg_kw: dict = dict(max_output_tokens=300, temperature=0.2)
    if MAIN_MODEL.startswith("gemini-3"):
        # Gemini 3.x думает по умолчанию и съедает бюджет ответа
        # (тот же приём, что main._thinking)
        cfg_kw["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
    response = await asyncio.to_thread(
        client.models.generate_content,
        model    = MAIN_MODEL,
        contents = _QUERY_PROMPT + query,
        config   = types.GenerateContentConfig(**cfg_kw),
    )
    mark_key_used(key)
    return _parse_model_queries(getattr(response, "text", None) or "")


async def build_search_queries(query: str) -> list[str]:
    """1-3 поисковых запроса из фразы Мастера: MAIN_MODEL, резерв _keywords().

    Именно здесь определяется качество поиска: модель сохраняет названия игр
    и точные названия навыков/предметов, разворачивает транслитерацию
    («ремнант фром зе эшс» → Remnant: From the Ashes) и добавляет уточняющий
    контекст (игра/платформа/год). Любой сбой → старое поведение _keywords().
    """
    query = (query or "").strip()
    if not query:
        return _keywords(query)
    try:
        queries = await _model_queries(query)
        # Поисковику нужны ASCII-кавычки (оператор точного совпадения),
        # а не типографские «»
        queries = [q.replace("«", '"').replace("»", '"') for q in queries]
        if queries:
            extra = _fallback_query(query)
            if extra and extra not in queries:
                queries.append(extra)   # подстраховка сырой фразой, ≤3 всего
            log.info(f"[parallel] queries (model): {queries[:3]}")
            return queries[:3]
        log.info(f"[parallel] queries (fallback): {_keywords(query)} — причина: ответ модели пуст")
    except Exception as e:
        log.info(f"[parallel] queries (fallback): {_keywords(query)} — причина: {type(e).__name__}: {e}")
    return _keywords(query)


def _parse_result(res: dict, max_results: int = 5) -> tuple[str, list[str], bool]:
    """tools/call web_search → (текст выдержек, URL, ok).

    Предпочитаем structuredContent (уже распарсенный), иначе парсим JSON
    из content[*].text. isError / пустой результат → ("", [], False).
    """
    if res.get("isError"):
        log.warning("[parallel] tool isError: %s", json.dumps(res, ensure_ascii=False)[:200])
        return "", [], False
    data = res.get("structuredContent") or {}
    if not data.get("results"):
        text = "".join(
            i.get("text", "") for i in (res.get("content") or [])
            if isinstance(i, dict) and i.get("type") == "text"
        )
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            data = {}
    results = (data or {}).get("results") or []
    parts: list[str] = []
    urls: list[str] = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        excerpts = [
            e.strip() for e in (item.get("excerpts") or [])
            if isinstance(e, str) and e.strip()
        ]
        if url:
            urls.append(url)
        if excerpts:
            head = f"{title}: " if title else ""
            parts.append(head + " ".join(excerpts))
    text = "\n\n".join(parts).strip()
    if not text:
        log.warning("[parallel] пустой результат поиска")
        return "", [], False
    return text, urls, True


async def parallel_search(query: str, max_results: int = 5) -> tuple[str, list[str], bool]:
    """Поиск через Parallel Search MCP. → (текст_выдержек, источники, ok).

    initialize → notifications/initialized → tools/call web_search.
    Сессия на один вызов (сервер stateless-friendly: заголовка
    Mcp-Session-Id может не быть — это нормально). При любом сбое —
    ("", [], False): вызывающая сторона честно скажет, что не нашла.
    """
    query = (query or "").strip()
    if not query:
        return "", [], False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # 1) initialize — установка сессии
            status, headers, msgs = await _rpc(client, None, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "sakura", "version": "1.0"},
                },
            })
            init = next((m for m in msgs if m.get("id") == 1), None)
            if status != 200 or not init or "result" not in init:
                log.warning(f"[parallel] initialize failed: HTTP {status}")
                return "", [], False
            sid = headers.get("mcp-session-id")

            # 2) notifications/initialized (202 без тела — норма)
            try:
                await _rpc(client, sid, {
                    "jsonrpc": "2.0", "method": "notifications/initialized",
                })
            except Exception as e:
                log.debug(f"[parallel] initialized notify: {type(e).__name__}: {e}")

            # 3) tools/call web_search — запросы составляет MAIN_MODEL
            # (лог "[parallel] queries (model|fallback)" — в build_search_queries)
            queries = await build_search_queries(query)
            args = {
                "objective": query,
                "search_queries": queries,
                "session_id": _SESSION_ID,
            }
            status, _, msgs = await _rpc(client, sid, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "web_search", "arguments": args},
            })
            called = next((m for m in msgs if m.get("id") == 2), None)
            if status != 200 or not called:
                log.warning(f"[parallel] tools/call failed: HTTP {status}")
                return "", [], False
            if "error" in called:
                log.warning(f"[parallel] json-rpc error: {json.dumps(called['error'], ensure_ascii=False)[:200]}")
                return "", [], False
            text, urls, ok = _parse_result(called.get("result") or {}, max_results)
            if ok:
                log.info(f"[parallel] ok: {len(urls)} источников, {len(text)} симв")
            return text, urls, ok
    except Exception as e:
        log.warning(f"[parallel] search failed: {type(e).__name__}: {e}")
        return "", [], False
