"""Живая проверка Gemma 4 для browser agent (S0). Запуск вручную, не в CI.

    venv/bin/python scripts/probe_gemma.py [--burst 20] [--models a,b]

Для каждой модели: картинка + текст, 3 кадра в одном запросе, нативный
function calling, response_schema, какие параметры генерации принимаются,
фактические лимиты (пачка запросов до 429, RetryInfo/QuotaFailure из ответа).
--nav-latency N — вместо проверок: задержка настоящего запроса навигатора
(build_request: цель, журнал, кадр, снимок, 14 инструментов) с мыслями по
умолчанию и с thinking_level=minimal, N пар попеременно.
Ключ — активный из config (окружение); не печатается и вычищается из
текстов ошибок. Вызовы — через sakura_core.llm.generate_raw (сырой ответ,
без фильтра параметров: проверяется, что принимает сама модель). Итог — markdown в stdout (переносится в docs/PROGRESS.md).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODELS = ("gemma-4-26b-a4b-it", "gemma-4-31b-it")
PACE_S = 4.5           # ≈13 RPM: проверки не должны сами упираться в 15 RPM
TIMEOUT_S = 90.0

_KEY = ""
_ONLY: tuple[str, ...] = ()


def _scrub(text: str) -> str:
    text = str(text)
    if _KEY:
        text = text.replace(_KEY, "<key>")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "<key>", text)[:300]


def _jpeg(color: tuple[int, int, int], label: str, size=(320, 200)) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 280, 160), fill=color)
    d.text((150, 175), label, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _error_info(e: Exception) -> dict:
    info = {"code": getattr(e, "code", None), "status": getattr(e, "status", None),
            "message": _scrub(getattr(e, "message", None) or e)}
    details = getattr(e, "details", None)
    err = details.get("error", details) if isinstance(details, dict) else {}
    for d in (err.get("details") or []) if isinstance(err, dict) else []:
        t = str(d.get("@type", ""))
        if t.endswith("RetryInfo"):
            info["retry_delay"] = d.get("retryDelay")
        elif t.endswith("QuotaFailure"):
            info["quota"] = [{k: v.get(k) for k in ("quotaMetric", "quotaId", "quotaValue")}
                             for v in d.get("violations") or []]
    return info


class Prober:
    def __init__(self, model: str):
        self.model = model
        self.last = 0.0
        self.rows: list[dict] = []
        self.calls = 0

    async def call(self, contents, *, pace=True, **cfg):
        from sakura_core.llm import generate_raw
        if pace:
            wait = self.last + PACE_S - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self.last = time.monotonic()
        self.calls += 1
        t0 = time.monotonic()
        cfg.setdefault("max_output_tokens", 256)
        resp = await generate_raw(self.model, contents, api_key=_KEY, timeout=TIMEOUT_S, **cfg)
        return resp, time.monotonic() - t0

    async def check(self, name: str, contents, judge, **cfg) -> dict:
        """Один вызов; 429 — ждать retry delay, 500/503 — до 3 повторов
        (иначе сбой бэкенда неотличим от «не поддерживается»)."""
        row = {"model": self.model, "check": name, "transient": []}
        if _ONLY and not any(o in name for o in _ONLY):
            return row
        for attempt in range(1, 5):
            try:
                resp, dt = await self.call(contents, **cfg)
                ok, detail = judge(resp)
                row.update(ok=ok, detail=detail, latency_s=round(dt, 2),
                           usage=_usage(resp))
                break
            except Exception as e:
                info = _error_info(e)
                if info.get("code") in (429, 500, 503) and attempt < 4:
                    row["transient"].append(info.get("code"))
                    delay = _seconds(info.get("retry_delay")) or 3.0 * 2 ** (attempt - 1)
                    await asyncio.sleep(delay + 1)
                    continue
                row.update(ok=False, error=info)
                break
        self.rows.append(row)
        print(f"  {self.model:22} {name:28} {'OK ' if row.get('ok') else 'ERR'} "
              f"{row.get('latency_s')}s retries={row['transient']} usage={row.get('usage')} "
              f"{row.get('detail') or row.get('error')}", file=sys.stderr)
        return row


def _seconds(delay) -> float | None:
    m = re.match(r"([\d.]+)s", str(delay or ""))
    return float(m.group(1)) if m else None


def _usage(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    return {"in": getattr(u, "prompt_token_count", None),
            "out": getattr(u, "candidates_token_count", None),
            "thoughts": getattr(u, "thoughts_token_count", None)} if u else {}


def _text(resp) -> str:
    try:
        return (resp.text or "").strip()
    except Exception:
        return ""


async def probe_model(model: str, burst: int) -> Prober:
    from google.genai import types as T
    p = Prober(model)
    img = lambda b: T.Part(inline_data=T.Blob(mime_type="image/jpeg", data=b))

    # 1. картинка + текст
    await p.check("image+text",
                  [img(_jpeg((220, 40, 40), "A")),
                   T.Part(text="What color is the big rectangle? One word.")],
                  lambda r: ("red" in _text(r).lower(), _text(r)[:60]))

    # 2. три кадра в одном запросе
    frames = [img(_jpeg(c, n)) for c, n in
              (((220, 40, 40), "1"), ((40, 160, 60), "2"), ((40, 80, 220), "3"))]
    await p.check("3 frames",
                  frames + [T.Part(text="Three images. Name the rectangle color in each, "
                                        "in order, comma-separated, one word each.")],
                  lambda r: (all(w in _text(r).lower() for w in ("red", "green", "blue"))
                             and _text(r).lower().index("red") < _text(r).lower().index("blue"),
                             _text(r)[:80]))

    # 3. нативный function calling
    tool = T.Tool(function_declarations=[T.FunctionDeclaration(
        name="page_act",
        description="Act on a page element.",
        parameters=T.Schema(type="OBJECT", properties={
            "ref": T.Schema(type="STRING"),
            "action": T.Schema(type="STRING", enum=["click", "type"]),
            "note": T.Schema(type="STRING")},
            required=["ref", "action", "note"]))])

    def judge_fc(r):
        calls = getattr(r, "function_calls", None) or []
        if calls:
            c = calls[0]
            return (c.name == "page_act", f"function_call {c.name}({json.dumps(dict(c.args or {}), ensure_ascii=False)[:80]})")
        return False, f"text: {_text(r)[:80]}"

    await p.check("function calling",
                  [T.Part(text="Page has button ref f0:e7 'Submit'. Click it. Use the tool.")],
                  judge_fc, tools=[tool],
                  automatic_function_calling=T.AutomaticFunctionCallingConfig(disable=True),
                  tool_config=T.ToolConfig(function_calling_config=T.FunctionCallingConfig(mode="ANY")))
    await p.check("function calling AUTO",
                  [T.Part(text="Page has button ref f0:e7 'Submit'. Click it.")],
                  judge_fc, tools=[tool],
                  automatic_function_calling=T.AutomaticFunctionCallingConfig(disable=True))

    # 4. response_schema
    schema = T.Schema(type="OBJECT", properties={
        "reasoning": T.Schema(type="STRING"),
        "answer": T.Schema(type="OBJECT", properties={
            "refs": T.Schema(type="ARRAY", items=T.Schema(type="STRING")),
            "text": T.Schema(type="STRING")})},
        required=["reasoning", "answer"])

    def judge_schema(r):
        try:
            obj = json.loads(_text(r))
            return ("answer" in obj and "reasoning" in obj, _text(r)[:80])
        except Exception:
            return False, f"not json: {_text(r)[:60]}"

    await p.check("response_schema",
                  [T.Part(text="Question: 2+2=? Options: f0:e1 '3', f0:e2 '4'. Pick the ref.")],
                  judge_schema, response_mime_type="application/json",
                  response_schema=schema, max_output_tokens=400)
    await p.check("response_mime json only",
                  [T.Part(text='Reply JSON {"x": 1}.')],
                  judge_schema_loose, response_mime_type="application/json")

    # 5. параметры генерации
    hi = [T.Part(text="Say hi.")]
    params = {
        "temperature=0.0": {"temperature": 0.0},
        "temperature=1.0": {"temperature": 1.0},
        "top_p=0.9": {"top_p": 0.9},
        "top_k=40": {"top_k": 40},
        "max_output_tokens=32": {"max_output_tokens": 32},
        "system_instruction": {"system_instruction": "You are terse."},
        "stop_sequences": {"stop_sequences": ["END"]},
        "seed=7": {"seed": 7},
        "presence_penalty=0.5": {"presence_penalty": 0.5},
        "frequency_penalty=0.5": {"frequency_penalty": 0.5},
        "candidate_count=1": {"candidate_count": 1},
        "safety_settings OFF": {"safety_settings": [T.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT", threshold="OFF")]},
        "thinking_level=minimal": {"thinking_config": T.ThinkingConfig(thinking_level="minimal")},
        "thinking_budget=0": {"thinking_config": T.ThinkingConfig(thinking_budget=0)},
        "response_logprobs": {"response_logprobs": True, "logprobs": 1},
    }
    for name, cfg in params.items():
        await p.check(f"param {name}", hi, lambda r: (bool(_text(r)), _text(r)[:30]), **cfg)

    # 6. лимиты: пачка без паузы до 429
    if burst:
        await asyncio.sleep(61)             # окно RPM с чистого листа
        t0 = time.monotonic()
        results = await asyncio.gather(*(
            _burst_one(p, hi) for _ in range(burst)), return_exceptions=False)
        ok = sum(1 for r in results if r is None)
        errs = [r for r in results if r is not None]
        codes: dict = {}
        for r in errs:
            codes[r.get("code")] = codes.get(r.get("code"), 0) + 1
        row = {"model": model, "check": f"burst {burst}", "ok": True,
               "detail": f"{ok} ok, ошибки {codes} за {time.monotonic() - t0:.1f}s"}
        limited = [r for r in errs if r.get("code") == 429]
        if limited:
            row["error"] = limited[0]
        p.rows.append(row)
        print(f"  {model:22} burst: {row['detail']} {errs[:1]}", file=sys.stderr)
    return p


def judge_schema_loose(r):
    try:
        json.loads(_text(r))
        return True, _text(r)[:40]
    except Exception:
        return False, f"not json: {_text(r)[:60]}"


async def _burst_one(p: Prober, contents):
    try:
        await p.call(contents, pace=False, max_output_tokens=8)
        return None
    except Exception as e:
        return _error_info(e)


def report(probers: list[Prober]) -> str:
    out = [f"### probe_gemma — {time.strftime('%Y-%m-%d %H:%M %Z')}", ""]
    checks = list(dict.fromkeys(r["check"] for p in probers for r in p.rows))
    out.append("| проверка | " + " | ".join(p.model for p in probers) + " |")
    out.append("|---|" + "---|" * len(probers))
    for c in checks:
        cells = []
        for p in probers:
            r = next((x for x in p.rows if x["check"] == c), None)
            if r is None:
                cells.append("—")
            elif r.get("ok"):
                retry = f" (повторы {r['transient']})" if r.get("transient") else ""
                cells.append("✅ " + str(r.get("detail", "")).replace("|", "/")[:60]
                             + f" {r.get('latency_s', '')}s" * ("latency_s" in r) + retry)
            else:
                e = r.get("error") or {}
                cells.append("❌ " + (f"{e.get('code')} {e.get('message', '')}" if e
                                     else str(r.get("detail", ""))).replace("|", "/")[:90])
        out.append(f"| {c} | " + " | ".join(cells) + " |")
    out.append("")
    for p in probers:
        for r in p.rows:
            e = r.get("error") or {}
            if e.get("quota") or e.get("retry_delay"):
                out.append(f"- {p.model} {r['check']}: retry_delay={e.get('retry_delay')} "
                           f"quota={json.dumps(e.get('quota'), ensure_ascii=False)}")
        out.append(f"- {p.model}: вызовов {p.calls}")
    return "\n".join(out)


def _nav_request():
    """Запрос навигатора как в бою: build_request (цель, журнал, кадр, снимок)."""
    from sakura_core import browser_step as bs
    from sakura_core import browser_task as bt
    task = bt.BrowserTask(task_id="probe", goal="Найди на странице форму обратной связи и "
                                                "отправь сообщение «тест»")
    for n, (tool, note) in enumerate((("page_observe", "смотрю страницу"),
                                      ("page_scroll", "листаю вниз к форме")), 1):
        task.step = n
        task.record(tool, note, status="done")
    task.step = 3
    task.add_frame(bt.Frame(step=3, frame_id="p", kind="page",
                            data=_jpeg((200, 200, 230), "form", size=(640, 400))))
    elements = [{"ref": f"f0:e{i}", "role": role, "name": name, "value": "",
                 "enabled": True, "in_viewport": True}
                for i, (role, name) in enumerate((
                    ("link", "Главная"), ("link", "О нас"), ("link", "Контакты"),
                    ("textbox", "Имя"), ("textbox", "Email"), ("textbox", "Сообщение"),
                    ("button", "Отправить"), ("link", "Политика")), 1)]
    obs = {"snapshot_id": "s3", "window_id": 1, "tab_id": 1, "url": "https://example.com/contact",
           "title": "Контакты", "elements": elements,
           "text": "Свяжитесь с нами. Заполните форму, и мы ответим в течение дня. " * 20}
    tools, tool_config = bs._tools()
    return bs.build_request(task, obs), {"system_instruction": bs.SYSTEM, "tools": tools,
                                         "tool_config": tool_config, "max_output_tokens": 2048}


async def nav_latency(model: str, n: int) -> str:
    """n пар запросов навигатора: мысли по умолчанию и thinking_level=minimal."""
    from google.genai import types as T
    contents, base = _nav_request()
    modes = {"по умолчанию": {},
             "minimal": {"thinking_config": T.ThinkingConfig(thinking_level="minimal")}}
    p = Prober(model)
    for i in range(n):
        for mode, extra in modes.items():
            await p.check(f"nav {mode} #{i + 1}", contents,
                          lambda r: (bool(getattr(r, "function_calls", None)),
                                     (r.function_calls[0].name if getattr(r, "function_calls", None)
                                      else "без вызова")),
                          automatic_function_calling=T.AutomaticFunctionCallingConfig(disable=True),
                          **base, **extra)
    lines = [f"### Задержка навигатора {model} — {time.strftime('%Y-%m-%d %H:%M %Z')}", "",
             "| режим | ок | медиана, с | мин–макс, с | thoughts (медиана) | повторов 500/503 |",
             "|---|---|---|---|---|---|"]
    for mode in modes:
        rows = [r for r in p.rows if r["check"].startswith(f"nav {mode} #")]
        ok = [r for r in rows if r.get("ok")]
        lat = sorted(r["latency_s"] for r in ok)
        th = sorted((r.get("usage") or {}).get("thoughts") or 0 for r in ok)
        retries = sum(len(r.get("transient") or []) for r in rows)
        med = lat[len(lat) // 2] if lat else "—"
        span = f"{lat[0]}–{lat[-1]}" if lat else "—"
        lines.append(f"| {mode} | {len(ok)}/{len(rows)} | {med} | {span} | "
                     f"{th[len(th) // 2] if th else '—'} | {retries} |")
    return "\n".join(lines)


async def main() -> None:
    global _KEY, _ONLY
    ap = argparse.ArgumentParser()
    ap.add_argument("--burst", type=int, default=20, help="0 — не проверять лимиты")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--only", default="", help="проверки по подстроке имени, через запятую")
    ap.add_argument("--nav-latency", type=int, default=0,
                    help="N пар запросов навигатора (мысли по умолчанию / minimal) вместо проверок")
    args = ap.parse_args()
    from config import get_active_key
    _KEY = get_active_key() or ""
    _ONLY = tuple(o.strip() for o in args.only.split(",") if o.strip())
    if not _KEY:
        raise SystemExit("нет активного ключа Gemini — проверка не запущена")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.nav_latency:
        for text in await asyncio.gather(*(nav_latency(m, args.nav_latency) for m in models)):
            print(text + "\n")
        return
    probers = await asyncio.gather(*(probe_model(m, args.burst) for m in models))
    print(report(list(probers)))


if __name__ == "__main__":
    asyncio.run(main())
