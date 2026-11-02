"""Замер решателя тестов на эталонном наборе (eval/quiz/bank.json).

Уровень 1 — только решатель (quiz_solver.solve) с теми же моделями,
лимитером квот и кадрами-вырезками, что в задаче браузера, но без браузера:
точность по категориям и видам вопросов, время, токены, сбои. Сквозной
прогон в Opera — следующий уровень (стенд desktop/tests/e2e/site).

Вопрос банка → форма решателя (как от page_questions): ref вариантов
«q<N>o<M>», строк сопоставления «q<N>r<M>». Ответ решателя → тексты
вариантов → сравнение с эталоном. Кадр: у вопросов с image — рисунок
(PIL), у прочих, кому в задаче нужна вырезка (needs_crop), — карточка с
текстом вопроса, как скриншот вопроса на странице.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("sakura.quiz_eval")

BANK_PATH = Path(__file__).resolve().parent.parent / "eval" / "quiz" / "bank.json"
KINDS = ("single", "multi", "select", "text", "number", "order", "match")
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "C:/Windows/Fonts/arial.ttf")


class BankError(ValueError):
    pass


# ── банк ───────────────────────────────────────────────────────────

def load_bank(path: Path | str = BANK_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    check_bank(items)
    return items


def check_bank(items: list[dict]) -> None:
    """Эталон согласован с вариантами; id уникальны; виды известны."""
    seen = set()
    for it in items:
        iid = it.get("id")
        if not iid or iid in seen:
            raise BankError(f"id пуст или повторяется: {iid}")
        seen.add(iid)
        kind, opts, ans = it.get("kind"), it.get("options") or [], it.get("answer")
        if kind not in KINDS:
            raise BankError(f"{iid}: вид {kind}")
        if not it.get("text") or not it.get("cat"):
            raise BankError(f"{iid}: нет текста или категории")
        if kind in ("single", "select") and ans not in opts:
            raise BankError(f"{iid}: ответ не из вариантов")
        if kind == "multi" and (not ans or any(a not in opts for a in ans)):
            raise BankError(f"{iid}: ответы не из вариантов")
        if kind == "order" and sorted(ans or []) != sorted(opts):
            raise BankError(f"{iid}: порядок — не перестановка вариантов")
        if kind == "match":
            rows = it.get("rows") or []
            if sorted((ans or {}).keys()) != sorted(rows) or any(v not in opts for v in ans.values()):
                raise BankError(f"{iid}: сопоставление не согласовано")
        if kind == "number" and not isinstance(ans, (int, float)):
            raise BankError(f"{iid}: number без числа")
        if kind == "text" and not (isinstance(ans, list) and ans):
            raise BankError(f"{iid}: text без вариантов ответа")


def select(items: list[dict], *, cats=None, ids=None, limit: int = 0) -> list[dict]:
    out = [it for it in items
           if (not cats or it["cat"] in cats) and (not ids or it["id"] in ids)]
    return out[:limit] if limit else out


def to_question(item: dict, index: int) -> dict:
    """Вопрос банка → форма решателя (как результат page_questions)."""
    q = {"index": index, "kind": item["kind"], "text": item["text"], "ref": f"q{index}",
         "has_media": bool(item.get("image"))}
    if item["kind"] == "match":
        q["rows"] = [{"ref": f"q{index}r{j}", "text": r} for j, r in enumerate(item["rows"])]
        q["options"] = [{"text": o} for o in item["options"]]
    elif item.get("options"):
        q["options"] = [{"ref": f"q{index}o{j}", "text": o} for j, o in enumerate(item["options"])]
    return q


# ── проверка ответа ────────────────────────────────────────────────

def norm_text(text) -> str:
    t = str(text or "").lower().replace("ё", "е")
    t = re.sub(r"[«»\"'“”„.,;:!?()\[\]]", " ", t)
    return " ".join(t.split())


_NUM = re.compile(r"[−-]?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?")


def parse_number(text) -> float | None:
    """Первое число в ответе: «0,25», «1/4», «−3», «28,26 см²»."""
    s = str(text or "").replace("\u2212", "-").replace("\u00a0", " ")
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)                  # 300 000
    m = _NUM.search(s)
    if not m:
        return None
    tok = m.group(0).replace(",", ".").replace(" ", "")
    try:
        if "/" in tok:
            a, b = tok.split("/")
            return float(a) / float(b)
        return float(tok)
    except (ValueError, ZeroDivisionError):
        return None


def grade(item: dict, question: dict, answer: dict | None) -> tuple[bool, float]:
    """(верно целиком, доля верного 0..1)."""
    if not answer:
        return False, 0.0
    kind, key = item["kind"], item["answer"]
    names = {o.get("ref"): o.get("text") for o in question.get("options") or []}
    if kind in ("single", "select"):
        got = [names.get(r) for r in answer.get("refs") or []]
        ok = got == [key]
        return ok, float(ok)
    if kind == "multi":
        got = {names.get(r) for r in answer.get("refs") or []}
        want = set(key)
        ok = got == want
        union = got | want
        return ok, (len(got & want) / len(union)) if union else 0.0
    if kind == "order":
        got = [names.get(r) for r in answer.get("order") or []]
        if not got and answer.get("pairs"):
            return False, 0.0
        ok = got == list(key)
        return ok, _kendall(got, list(key))
    if kind == "match":
        rows = {r["ref"]: r["text"] for r in question.get("rows") or []}
        got = {rows.get(p.get("row_ref")): p.get("option_text") for p in answer.get("pairs") or []}
        hits = sum(1 for r, v in key.items() if norm_text(got.get(r)) == norm_text(v))
        return hits == len(key), hits / len(key)
    if kind == "number":
        val = parse_number(answer.get("text"))
        if val is None:
            return False, 0.0
        tol = float(item.get("tol", 1e-6))
        ok = math.isclose(val, float(key), abs_tol=tol, rel_tol=0)
        return ok, float(ok)
    got = norm_text(answer.get("text"))
    accepted = [norm_text(a) for a in key]
    if item.get("match") == "contains":
        ok = any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", got) for a in accepted)
    else:
        ok = got in accepted
    return ok, float(ok)


def _kendall(got: list, want: list) -> float:
    """Доля правильно упорядоченных пар (1 — всё верно)."""
    if sorted(map(str, got)) != sorted(map(str, want)) or len(want) < 2:
        return 0.0
    pos = {v: i for i, v in enumerate(got)}
    pairs = [(a, b) for i, a in enumerate(want) for b in want[i + 1:]]
    return sum(1 for a, b in pairs if pos[a] < pos[b]) / len(pairs)


# ── кадры ──────────────────────────────────────────────────────────

def _font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def has_cyrillic_font() -> bool:
    return any(Path(p).is_file() for p in FONT_PATHS)


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in str(text).split():
        if len(line) + len(word) + 1 > width and line:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return out + ([line] if line else [])


def render_crop(item: dict, question: dict) -> bytes:
    """JPEG как вырезка вопроса со страницы: текст, варианты, рисунок."""
    from PIL import Image, ImageDraw
    w, lh = 760, 26
    head = _wrap(f"{question['index']}. {item['text']}", 70)
    tail = [f"   {r['text']}  [выбрать ▾]" for r in question.get("rows") or []]
    if item["kind"] == "match":
        tail.append("   Варианты: " + " · ".join(o["text"] for o in question.get("options") or []))
    elif item["kind"] in ("text", "number"):
        tail.append("   Ответ: [____________]")
    else:
        mark = {"multi": "☐", "single": "○", "order": "≡"}.get(item["kind"], "•")
        tail += [f" {mark} {o['text']}" for o in question.get("options") or []]
    fig_h = 300 if item.get("image") else 0
    h = 36 + lh * (len(head) + len(tail)) + fig_h + 20
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    f = _font(18)
    y = 18
    for ln in head:
        d.text((20, y), ln, fill="black", font=f)
        y += lh
    if fig_h:
        _draw_figure(d, item["image"], (40, y + 10, w - 40, y + fig_h - 10))
        y += fig_h
    for ln in tail:
        d.text((20, y), ln, fill="black", font=f)
        y += lh
    d.rectangle((2, 2, w - 3, h - 3), outline="#bbbbbb")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _draw_figure(d, spec: dict, box) -> None:
    x0, y0, x1, y1 = box
    f = _font(18)
    t = spec.get("type")
    if t == "bars":
        vals, labels = spec["values"], spec["labels"]
        top = max(vals)
        bw = (x1 - x0) / (len(vals) * 1.6)
        d.line((x0, y1 - 24, x1, y1 - 24), fill="black")
        for i, (v, lab) in enumerate(zip(vals, labels, strict=True)):
            bx = x0 + 20 + i * bw * 1.6
            bh = (y1 - y0 - 50) * v / top
            d.rectangle((bx, y1 - 24 - bh, bx + bw, y1 - 24), fill="#4a7fd4")
            d.text((bx, y1 - 22), lab, fill="black", font=f)
    elif t == "shapes":
        n = spec["circles"] + spec["squares"]
        kinds = (["c"] * spec["circles"] + ["s"] * spec["squares"])
        kinds = [kinds[(i * 5) % n] for i in range(n)]          # перемешано детерминированно
        cols = 6
        for i, k in enumerate(kinds):
            cx = x0 + 40 + (i % cols) * 95
            cy = y0 + 50 + (i // cols) * 100
            if k == "c":
                d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), outline="black", width=3)
            else:
                d.rectangle((cx - 28, cy - 28, cx + 28, cy + 28), outline="black", width=3)
    elif t == "text":
        d.text((x0 + 40, (y0 + y1) // 2 - 20), spec["text"], fill="black", font=_font(40))
    elif t == "triangle":
        a = (x0 + 60, y1 - 30)
        b = (x0 + 60, y0 + 30)
        c = (x0 + 460, y1 - 30)
        d.polygon([a, b, c], outline="black", width=3)
        d.rectangle((a[0], a[1] - 20, a[0] + 20, a[1]), outline="black")
        d.text((a[0] - 40, (a[1] + b[1]) // 2), spec["a"], fill="black", font=f)
        d.text(((a[0] + c[0]) // 2, a[1] + 4), spec["b"], fill="black", font=f)
        d.text(((b[0] + c[0]) // 2 + 10, (b[1] + c[1]) // 2 - 20), "?", fill="black", font=f)
    elif t == "table":
        rows = [spec["header"]] + spec["rows"]
        cw, rh = 230, 40
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                bx, by = x0 + c * cw, y0 + r * rh
                d.rectangle((bx, by, bx + cw, by + rh), outline="black")
                d.text((bx + 8, by + 10), cell, fill="black", font=f)
    elif t == "clock":
        cx, cy, r = (x0 + x1) // 2, (y0 + y1) // 2, 120
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline="black", width=4)
        for h in range(12):
            ang = math.radians(h * 30 - 90)
            d.line((cx + (r - 15) * math.cos(ang), cy + (r - 15) * math.sin(ang),
                    cx + r * math.cos(ang), cy + r * math.sin(ang)), fill="black", width=3)
        ha = math.radians((spec["hour"] % 12 + spec["minute"] / 60) * 30 - 90)
        ma = math.radians(spec["minute"] * 6 - 90)
        d.line((cx, cy, cx + 60 * math.cos(ha), cy + 60 * math.sin(ha)), fill="black", width=8)
        d.line((cx, cy, cx + 100 * math.cos(ma), cy + 100 * math.sin(ma)), fill="black", width=4)
    elif t == "colors":
        d.ellipse((x0 + 20, y0 + 60, x0 + 160, y0 + 200), fill="#d62828")
        d.polygon([(x0 + 280, y0 + 200), (x0 + 350, y0 + 60), (x0 + 420, y0 + 200)], fill="#1d4ed8")
        d.rectangle((x0 + 520, y0 + 60, x0 + 660, y0 + 200), fill="#2a9d3f")


# ── прогон ─────────────────────────────────────────────────────────

@dataclass
class Result:
    id: str
    cat: str
    kind: str
    ok: bool = False
    score: float = 0.0
    seconds: float = 0.0                 # весь вопрос, с ожиданием квот
    model_seconds: list = field(default_factory=list)   # каждая попытка вызова
    model: str = ""
    tokens: int = 0
    crop: bool = False
    error: str = ""
    got: str = ""
    want: str = ""


async def solve_one(item: dict, index: int, *, crops: bool, limiter, solve=None,
                    max_quota_wait: float = 300.0, sleep=asyncio.sleep) -> Result:
    from sakura_core import quiz_solver as qs
    from sakura_core.llm import ChainExhausted, QuotaWait
    solve = solve or qs.solve
    q = to_question(item, index)
    res = Result(id=item["id"], cat=item["cat"], kind=item["kind"],
                 want=_label_key(item))
    crop = render_crop(item, q) if crops and qs.needs_crop(q) else None
    res.crop = crop is not None

    def on_event(kind, **data):
        if kind == "call":
            res.model_seconds.append(round(float(data.get("latency") or 0), 2))

    started = time.monotonic()
    waited = 0.0
    while True:
        try:
            out = await solve(q, crop, limiter=limiter, on_event=on_event)
            break
        except QuotaWait as e:
            if waited + e.retry_after > max_quota_wait:
                res.error = "quota_wait"
                res.seconds = round(time.monotonic() - started, 2)
                return res
            waited += e.retry_after
            await sleep(e.retry_after)
        except ChainExhausted as e:
            res.error = f"chain_exhausted:{getattr(e, 'reason', '')}"
            res.seconds = round(time.monotonic() - started, 2)
            return res
        except Exception as e:  # noqa: BLE001 — сбой одного вопроса не роняет замер
            res.error = type(e).__name__
            res.seconds = round(time.monotonic() - started, 2)
            return res
    res.seconds = round(time.monotonic() - started, 2)
    res.model, res.tokens = out.get("model", ""), int(out.get("tokens") or 0)
    res.ok, res.score = grade(item, q, out.get("answer"))
    res.got = _label_answer(q, out.get("answer"))
    return res


def _label_key(item: dict) -> str:
    key = item["answer"]
    if isinstance(key, dict):
        return "; ".join(f"{k} → {v}" for k, v in key.items())
    if isinstance(key, list):
        return " | ".join(map(str, key))
    return str(key)


def _label_answer(question: dict, answer: dict | None) -> str:
    if not answer:
        return ""
    from sakura_core.quiz_solver import answer_label
    try:
        return answer_label(question, answer)
    except Exception:  # noqa: BLE001
        return json.dumps(answer, ensure_ascii=False)[:200]


async def run(items: list[dict], *, parallel: int = 3, crops: bool = True,
              limiter=None, solve=None, progress=None) -> list[Result]:
    """Все вопросы, до parallel одновременно (как пакеты решателя в задаче)."""
    from sakura_core.rate_limiter import RateLimiter
    limiter = limiter or RateLimiter(path=None)
    sem = asyncio.Semaphore(max(1, parallel))
    done = 0

    async def one(i, item):
        nonlocal done
        async with sem:
            r = await solve_one(item, i + 1, crops=crops, limiter=limiter, solve=solve)
        done += 1
        if progress:
            progress(done, len(items), r)
        return r

    return list(await asyncio.gather(*(one(i, it) for i, it in enumerate(items))))


# ── отчёт ──────────────────────────────────────────────────────────

def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    return round(vs[min(len(vs) - 1, max(0, math.ceil(q * len(vs)) - 1))], 2)


def _group(results: list[Result], key) -> dict:
    out: dict[str, dict] = {}
    for r in results:
        g = out.setdefault(key(r), {"n": 0, "ok": 0, "score": 0.0, "errors": 0})
        g["n"] += 1
        g["ok"] += int(r.ok)
        g["score"] += r.score
        g["errors"] += int(bool(r.error))
    for g in out.values():
        g["acc"] = round(g["ok"] / g["n"], 3)
        g["score"] = round(g["score"] / g["n"], 3)
    return dict(sorted(out.items()))


def summarize(results: list[Result], *, meta: dict | None = None, wall: float = 0.0) -> dict:
    n = len(results)
    secs = [r.seconds for r in results if not r.error]
    calls = [s for r in results for s in r.model_seconds]
    models: dict[str, int] = {}
    for r in results:
        if r.model:
            models[r.model] = models.get(r.model, 0) + 1
    return {
        "meta": meta or {},
        "n": n,
        "accuracy": round(sum(r.ok for r in results) / n, 3) if n else 0.0,
        "score": round(sum(r.score for r in results) / n, 3) if n else 0.0,
        "errors": sum(1 for r in results if r.error),
        "by_cat": _group(results, lambda r: r.cat),
        "by_kind": _group(results, lambda r: r.kind),
        "question_seconds": {"p50": _pct(secs, 0.5), "p90": _pct(secs, 0.9), "max": _pct(secs, 1.0),
                             "mean": round(statistics.fmean(secs), 2) if secs else 0.0},
        "call_seconds": {"p50": _pct(calls, 0.5), "p90": _pct(calls, 0.9), "max": _pct(calls, 1.0),
                         "calls": len(calls)},
        "wall_seconds": round(wall, 1),
        "tokens": sum(r.tokens for r in results),
        "models": models,
        "wrong": [{"id": r.id, "want": r.want, "got": r.got, "error": r.error}
                  for r in results if not r.ok],
        "results": [asdict(r) for r in results],
    }


def to_markdown(rep: dict) -> str:
    m = rep.get("meta") or {}
    qs, cs = rep["question_seconds"], rep["call_seconds"]
    lines = [
        f"# Замер решателя — {m.get('started', '')}",
        "",
        f"Модели: {', '.join(m.get('chain') or [])} · параллельно {m.get('parallel')} · "
        f"кадры {'да' if m.get('crops') else 'нет'} · вопросов {rep['n']}",
        "",
        f"**Точность {rep['accuracy'] * 100:.1f}%** (частичные ответы: {rep['score'] * 100:.1f}%), "
        f"сбоев {rep['errors']}, токенов {rep['tokens']}, весь прогон {rep['wall_seconds']} с.",
        "",
        f"Вопрос: p50 {qs['p50']} с, p90 {qs['p90']} с, макс {qs['max']} с. "
        f"Вызов модели: p50 {cs['p50']} с, p90 {cs['p90']} с, макс {cs['max']} с ({cs['calls']} вызовов).",
        "",
        "| категория | n | верно | точность | сбои |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {k} | {g['n']} | {g['ok']} | {g['acc'] * 100:.0f}% | {g['errors']} |"
              for k, g in rep["by_cat"].items()]
    lines += ["", "| вид | n | верно | точность |", "|---|---|---|---|"]
    lines += [f"| {k} | {g['n']} | {g['ok']} | {g['acc'] * 100:.0f}% |" for k, g in rep["by_kind"].items()]
    if rep["wrong"]:
        lines += ["", "Ошибки:", ""]
        lines += [f"- `{w['id']}` — нужно «{w['want']}», ответ «{w['got'] or '—'}»"
                  + (f" ({w['error']})" if w["error"] else "") for w in rep["wrong"]]
    return "\n".join(lines) + "\n"


def compare(a: dict, b: dict) -> str:
    """Таблица «было → стало» по двум отчётам."""
    def row(name, x, y, pct=True, unit=""):
        if pct:
            return f"| {name} | {x * 100:.1f}% | {y * 100:.1f}% | {(y - x) * 100:+.1f} п.п. |"
        return f"| {name} | {x}{unit} | {y}{unit} | {y - x:+.2f}{unit} |"
    lines = ["| | A | B | Δ |", "|---|---|---|---|",
             row("точность", a["accuracy"], b["accuracy"]),
             row("частичные", a["score"], b["score"]),
             row("вопрос p50", a["question_seconds"]["p50"], b["question_seconds"]["p50"], False, " с"),
             row("вопрос p90", a["question_seconds"]["p90"], b["question_seconds"]["p90"], False, " с"),
             row("весь прогон", a["wall_seconds"], b["wall_seconds"], False, " с"),
             f"| токены | {a['tokens']} | {b['tokens']} | {b['tokens'] - a['tokens']:+d} |",
             f"| сбои | {a['errors']} | {b['errors']} | {b['errors'] - a['errors']:+d} |"]
    for cat in sorted(set(a["by_cat"]) | set(b["by_cat"])):
        x = a["by_cat"].get(cat, {}).get("acc", 0.0)
        y = b["by_cat"].get(cat, {}).get("acc", 0.0)
        lines.append(row(f"· {cat}", x, y))
    ids_a = {r["id"] for r in a["results"] if r["ok"]}
    ids_b = {r["id"] for r in b["results"] if r["ok"]}
    fixed, broke = sorted(ids_b - ids_a), sorted(ids_a - ids_b)
    lines += ["", f"Исправлено: {', '.join(fixed) or '—'}", f"Сломано: {', '.join(broke) or '—'}"]
    return "\n".join(lines) + "\n"
