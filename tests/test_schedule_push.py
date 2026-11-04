"""Приём расписания из букмарклета: авторизация, CORS, лимиты, итог."""
# Наивное локальное время — как в коде Сакуры (R10).
# ruff: noqa: DTZ001

import asyncio
import json
import logging
from datetime import datetime

from aiohttp.test_utils import TestClient, TestServer

import config
from sakura_core.schedule.push_server import (
    ALLOWED_ORIGIN,
    MAX_BODY,
    RATE_PER_HOUR,
    make_app,
)
from sakura_core.schedule.sync import SyncResult
from tests.schedule_support import FIXTURE

TOKEN = "t0ken-for-tests-only"


def run(scenario, **kw):
    calls = []

    async def ingest(ttable, now):
        calls.append(ttable)
        return SyncResult(True, "push", count=5)

    async def main():
        clock = {"t": 0.0}
        app = make_app(token=TOKEN, ingest=kw.get("ingest", ingest),
                       clock=lambda: datetime(2026, 11, 4, 12), monotonic=lambda: clock["t"])
        async with TestClient(TestServer(app)) as client:
            return await scenario(client, clock)
    return asyncio.run(main()), calls


def body(group=None, tt=None):
    return json.dumps({"group": group or config.MUIV_GROUP,
                       "ttable": tt if tt is not None else FIXTURE.read_text(encoding="utf-8")})


H = {"Authorization": f"Bearer {TOKEN}", "Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"}


def test_success_and_cors():
    async def sc(c, _):
        r = await c.post("/schedule/push", data=body(), headers=H)
        return r.status, await r.json(), r.headers.get("Access-Control-Allow-Origin")
    (status, js, cors), calls = run(sc)
    assert status == 200 and js == {"ok": True, "message": "5 занятий, без изменений"}
    assert cors == ALLOWED_ORIGIN and len(calls) == 1


def test_preflight():
    async def sc(c, _):
        r = await c.options("/schedule/push", headers={"Origin": ALLOWED_ORIGIN,
                                                       "Access-Control-Request-Method": "POST"})
        return r.status, r.headers.get("Access-Control-Allow-Headers")
    (status, allow), _ = run(sc)
    assert status == 204 and "Authorization" in allow


def test_auth_required():
    async def sc(c, _):
        a = await c.post("/schedule/push", data=body(), headers={**H, "Authorization": ""})
        b = await c.post("/schedule/push", data=body(), headers={**H, "Authorization": "Bearer wrong"})
        return a.status, b.status
    (st, calls) = run(sc)
    assert st == (401, 401) and calls == []


def test_foreign_origin_rejected():
    async def sc(c, _):
        r = await c.post("/schedule/push", data=body(), headers={**H, "Origin": "https://evil.example"})
        return r.status, r.headers.get("Access-Control-Allow-Origin")
    (st, cors), calls = run(sc)
    assert st == 403 and cors is None and calls == []


def test_wrong_group_and_bad_json():
    async def sc(c, _):
        a = await c.post("/schedule/push", data=body(group="ИД 23.1/Б1-25"), headers=H)
        b = await c.post("/schedule/push", data="not json", headers=H)
        d = await c.post("/schedule/push", data=json.dumps({"group": config.MUIV_GROUP}), headers=H)
        return a.status, b.status, d.status
    (st, calls) = run(sc)
    assert st == (400, 400, 400) and calls == []


def test_too_big():
    async def sc(c, _):
        r = await c.post("/schedule/push", data=body(tt="x" * (MAX_BODY + 10)), headers=H)
        return r.status
    (st, calls) = run(sc)
    assert st == 413 and calls == []


def test_rate_limit_resets_after_hour():
    async def sc(c, clock):
        codes = [(await c.post("/schedule/push", data=body(), headers=H)).status
                 for _ in range(RATE_PER_HOUR + 1)]
        clock["t"] = 3601.0
        codes.append((await c.post("/schedule/push", data=body(), headers=H)).status)
        return codes
    (codes, _) = run(sc)
    assert codes[:RATE_PER_HOUR] == [200] * RATE_PER_HOUR
    assert codes[RATE_PER_HOUR] == 429 and codes[-1] == 200


def test_ingest_failure_is_422_with_reason():
    async def bad(ttable, now):
        return SyncResult(False, "push", error="not_schedule")

    async def sc(c, _):
        r = await c.post("/schedule/push", data=body(), headers=H)
        return r.status, (await r.json())["message"]
    (st, msg), _ = run(sc, ingest=bad)
    assert st == 422 and "не расписание" in msg


def test_token_and_ttable_never_logged(caplog):
    caplog.set_level(logging.DEBUG)

    async def sc(c, _):
        await c.post("/schedule/push", data=body(), headers=H)
        await c.post("/schedule/push", data=body(), headers={**H, "Authorization": "Bearer nope"})
    run(sc)
    text = caplog.text
    assert TOKEN not in text and "nope" not in text and "Технологическая" not in text


def test_serve_without_token_exits(monkeypatch):
    from sakura_core.schedule import push_server
    monkeypatch.setattr(config, "SCHEDULE_PUSH_TOKEN", "")
    asyncio.run(asyncio.wait_for(push_server.serve(), 1))
