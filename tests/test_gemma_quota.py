"""server/browser-step S2/S3: квоты Gemma (RPM, RPD) и 429 в вызовах агента.

Run: python -m pytest tests/test_gemma_quota.py -q
"""

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest

import config
from sakura_core import llm
from sakura_core import rate_limiter as rl


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ── S2: token bucket и RPD ───────────────────────────────────────────

def test_token_bucket_rpm(tmp_path):
    clock = Clock()
    lim = rl.RateLimiter(rpm=15, rpd=1500, path=None, clock=clock, tpm=0)
    for _ in range(15):
        assert lim.wait("m") == 0
        lim.take("m")
    assert lim.wait("m") == pytest.approx(4.0)
    clock.t += 4.0
    assert lim.wait("m") == 0
    assert lim.wait("other") == 0          # квота — на каждую модель отдельно


def test_rpd_resets_at_pacific_midnight(tmp_path):
    path = tmp_path / "quota.json"
    pt = rl.PT
    start = dt.datetime(2026, 10, 26, 23, 0, tzinfo=pt).timestamp()
    clock = Clock(start)
    lim = rl.RateLimiter(rpm=1000, rpd=3, path=path, clock=clock)
    for _ in range(3):
        lim.take("m")
    until = lim.exhausted_until("m")
    assert until == dt.datetime(2026, 10, 27, 0, 0, tzinfo=pt).timestamp()
    assert lim.wait("m") == pytest.approx(3600)
    # персистентно: новый процесс видит расход
    again = rl.RateLimiter(rpm=1000, rpd=3, path=path, clock=clock)
    assert again.used("m") == 3 and again.exhausted_until("m") is not None
    clock.t = until + 1
    assert again.exhausted_until("m") is None and again.used("m") == 0
    assert json.loads(path.read_text())["day"] == "2026-10-27"


# ── S3: 429 ──────────────────────────────────────────────────────────

class ApiError(Exception):
    def __init__(self, code, delay=None, per_day=False):
        super().__init__(f"{code} RESOURCE_EXHAUSTED" if code == 429 else f"{code} INTERNAL")
        self.code = code
        details = []
        if delay:
            details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": f"{delay}s"})
        if per_day:
            details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]})
        self.details = {"error": {"code": code, "details": details}}


def _raw_script(monkeypatch, script):
    seen = []

    async def raw(model, contents, **cfg):
        seen.append(model)
        item = script[model].pop(0) if script[model] else "ok"
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text="ok", usage_metadata=SimpleNamespace(total_token_count=5))

    monkeypatch.setattr(llm, "generate_raw", raw)
    return seen


def test_429_retry_delay_from_response(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    _raw_script(monkeypatch, {"a": [ApiError(429, delay=7)], "b": []})
    with pytest.raises(llm.QuotaWait) as e:
        asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim))
    assert e.value.retry_after == pytest.approx(7)       # уважаем retryDelay, b не трогаем


def test_429_backoff_then_next_model(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    seen = _raw_script(monkeypatch, {"a": [ApiError(429)] * 6, "b": []})
    sleeps = []

    async def sleep(s):
        sleeps.append(round(s, 3))
        clock.t += s

    res = asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim,
                                         inline_wait=100, sleep=sleep))
    assert res.model == "b"
    assert seen == ["a"] * 6 + ["b"]                       # 1 + 5 повторов, затем b
    assert [s for s in sleeps if s >= 1] == [4, 8, 16, 32, 32]


def test_chain_exhausted_per_day(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    _raw_script(monkeypatch, {"a": [ApiError(429, per_day=True)],
                              "b": [ApiError(429, per_day=True)]})
    with pytest.raises(llm.ChainExhausted) as e:
        asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim))
    assert e.value.resume_at == rl.next_reset(clock.t)


def test_agent_call_filters_gemma_params(monkeypatch):
    monkeypatch.setattr(config, "GEMMA_PARAMS", ("max_output_tokens", "tools", "tool_config",
                                                 "automatic_function_calling"))
    got = {}

    async def raw(model, contents, timeout=None, **cfg):
        got.update(cfg)
        return SimpleNamespace(text="ok", usage_metadata=None)

    monkeypatch.setattr(llm, "generate_raw", raw)
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None)
    asyncio.run(llm.generate_agent(["x"], chain=("gemma-4-26b-a4b-it",), limiter=lim,
                                   temperature=0.3, response_mime_type="application/json"))
    assert set(got) == {"max_output_tokens"}


def test_500_retries_5_10_20_then_next_model(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    seen = _raw_script(monkeypatch, {"a": [ApiError(500)] * 4, "b": []})
    sleeps = []

    async def sleep(s):
        sleeps.append(round(s, 3))
        clock.t += s

    res = asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim,
                                         inline_wait=100, sleep=sleep))
    assert res.model == "b" and seen == ["a"] * 4 + ["b"]
    assert [s for s in sleeps if s >= 1] == [5, 10, 20]


def test_503_long_wait_goes_to_desktop_and_all_down_pauses(monkeypatch):
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock)
    seen = _raw_script(monkeypatch, {"a": [ApiError(503)], "b": []})
    with pytest.raises(llm.QuotaWait) as e:              # 5 с > inline_wait: ждёт desktop
        asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim, inline_wait=1))
    assert e.value.retry_after == pytest.approx(5) and seen == ["a"]   # b не трогаем

    clock2 = Clock()
    lim2 = rl.RateLimiter(rpm=100, rpd=100, path=None, clock=clock2)
    _raw_script(monkeypatch, {"a": [ApiError(500)] * 4, "b": [ApiError(500)] * 4})

    async def sleep(s):
        clock2.t += s

    with pytest.raises(llm.ChainExhausted) as e:
        asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim2,
                                       inline_wait=100, sleep=sleep))
    assert e.value.reason == "unavailable"
    assert e.value.resume_at == pytest.approx(clock2.t - 35 + rl.SERVER_BLOCK_S)
    assert lim2.exhausted_reason("a") == "unavailable"


# ── TPM (прогон 28.10: 429 при 5–8 вызовах/мин по 2–4 тыс. токенов) ───

def test_tpm_bucket_reserves_and_waits():
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=1000, path=None, clock=clock, tpm=10000)
    assert lim.estimate("m") == rl.TPM_DEFAULT_COST
    for _ in range(3):
        assert lim.wait("m") == 0
        lim.take("m")                                   # 3 × 3000 → остаток 1000
    assert lim.wait("m") == pytest.approx((3000 - 1000) * 60 / 10000)
    clock.t += 12
    assert lim.wait("m") == pytest.approx(0, abs=1e-6)
    assert lim.wait("other") == 0                       # бакет — на модель


def test_tpm_corrects_reservation_by_actual_usage():
    clock = Clock()
    lim = rl.RateLimiter(rpm=100, rpd=1000, path=None, clock=clock, tpm=6000)
    r1 = lim.take("m")
    r2 = lim.take("m")                                  # 6000 зарезервировано, 0 осталось
    assert lim.wait("m") > 0
    lim.on_tokens("m", 1000, r1)                        # факт 1000: 2000 назад
    lim.on_tokens("m", 0, r2)                           # вызов не дошёл: 3000 назад
    assert lim.wait("m") == 0
    assert lim.estimate("m") == 1000                    # оценка — по факту


def test_tpm_zero_disables():
    lim = rl.RateLimiter(rpm=100, rpd=1000, path=None, tpm=0)
    for _ in range(50):
        assert lim.wait("m") == 0 and lim.take("m") == 0.0


def test_quota_ids_logged_on_429(monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO)
    err = ApiError(429, delay=21)
    err.details["error"]["details"].append(
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier"}]})
    assert llm.quota_ids(err) == ["GenerateContentInputTokensPerModelPerMinute-FreeTier"]
    _raw_script(monkeypatch, {"a": [err], "b": []})
    lim = rl.RateLimiter(rpm=100, rpd=100, path=None, tpm=0)
    with pytest.raises(llm.QuotaWait):
        asyncio.run(llm.generate_agent(["x"], chain=("a", "b"), limiter=lim))
    assert ("429 model=a quota=GenerateContentInputTokensPerModelPerMinute-FreeTier "
            "retry_delay=21.0") in caplog.text
