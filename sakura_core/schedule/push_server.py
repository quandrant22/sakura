"""Приём расписания из браузера Мастера (источник push, букмарклет).

POST /schedule/push   {"group": "...", "ttable": "<h2>…"}
Authorization: Bearer <SCHEDULE_PUSH_TOKEN>

Слушает только SCHEDULE_PUSH_HOST (по умолчанию 127.0.0.1); наружу — через
Caddy (Caddyfile.example, handle /schedule/push). CORS — только для страницы
вуза. Токен сравнивается за постоянное время и никуда не пишется. Пустой
токен — приёмник не запускается.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from collections import deque
from datetime import datetime

from aiohttp import web

import config

log = logging.getLogger("sakura.schedule")

ALLOWED_ORIGIN = "https://www.muiv.ru"
MAX_BODY = 256 * 1024
RATE_PER_HOUR = 10


def _cors(resp: web.StreamResponse, origin: str | None) -> web.StreamResponse:
    if origin == ALLOWED_ORIGIN:
        resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Max-Age"] = "600"
        resp.headers["Vary"] = "Origin"
    return resp


def make_app(*, token: str | None = None, ingest=None, clock=datetime.now,
             monotonic=time.monotonic) -> web.Application:
    secret = (token if token is not None else config.SCHEDULE_PUSH_TOKEN).encode()
    hits: deque[float] = deque()

    if ingest is None:
        from sakura_core.schedule.sync import ingest as _ingest

        async def ingest(ttable: str, now: datetime):
            return await asyncio.to_thread(_ingest, ttable, "push", now)

    def reply(request, status: int, ok: bool, message: str) -> web.Response:
        resp = web.json_response({"ok": ok, "message": message}, status=status)
        return _cors(resp, request.headers.get("Origin"))

    async def options(request: web.Request) -> web.StreamResponse:
        return _cors(web.Response(status=204), request.headers.get("Origin"))

    async def push(request: web.Request) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        if origin is not None and origin != ALLOWED_ORIGIN:
            return reply(request, 403, False, "origin")
        auth = request.headers.get("Authorization", "")
        given = auth[7:].encode() if auth.startswith("Bearer ") else b""
        if not secret or not hmac.compare_digest(given, secret):
            log.info("[schedule] push: отказ (токен)")
            return reply(request, 401, False, "unauthorized")
        now_m = monotonic()
        while hits and now_m - hits[0] > 3600:
            hits.popleft()
        if len(hits) >= RATE_PER_HOUR:
            return reply(request, 429, False, "слишком часто, попробуй через час")
        hits.append(now_m)
        if (request.content_length or 0) > MAX_BODY:
            return reply(request, 413, False, "слишком большой запрос")
        try:
            raw = await request.content.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                return reply(request, 413, False, "слишком большой запрос")
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return reply(request, 400, False, "нужен JSON")
        if not isinstance(body, dict) or not isinstance(body.get("ttable"), str):
            return reply(request, 400, False, "нет ttable")
        if body.get("group") != config.MUIV_GROUP:
            return reply(request, 400, False, f"группа не та: жду {config.MUIV_GROUP}")
        res = await ingest(body["ttable"], clock())
        return reply(request, 200 if res.ok else 422, res.ok, res.summary())

    app = web.Application(client_max_size=MAX_BODY)
    app.router.add_route("OPTIONS", "/schedule/push", options)
    app.router.add_post("/schedule/push", push)
    return app


async def serve() -> None:
    """Фоновая задача main.py. Без токена — тихо выходит."""
    if not config.SCHEDULE_PUSH_TOKEN:
        log.info("[schedule] приём push выключен: нет SCHEDULE_PUSH_TOKEN")
        return
    runner = web.AppRunner(make_app(), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.SCHEDULE_PUSH_HOST, config.SCHEDULE_PUSH_PORT)
    await site.start()
    log.info(f"[schedule] приём push: {config.SCHEDULE_PUSH_HOST}:{config.SCHEDULE_PUSH_PORT}")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
