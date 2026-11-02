"""Замер решателя: набор, перевод в форму решателя, проверка ответов, отчёт."""

import asyncio
import json

import pytest

from sakura_core import quiz_eval as qe
from sakura_core import quiz_solver as qs


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def bank():
    return qe.load_bank()


def perfect(item, q):
    """Ответ, который дал бы идеальный решатель, — в форме quiz_solver.validate."""
    ref = {o["text"]: o.get("ref") for o in q.get("options") or []}
    k, key = item["kind"], item["answer"]
    if k in ("single", "select"):
        return {"refs": [ref[key]]}
    if k == "multi":
        return {"refs": [ref[x] for x in key]}
    if k == "order":
        return {"order": [ref[x] for x in key]}
    if k == "match":
        rows = {r["text"]: r["ref"] for r in q["rows"]}
        return {"pairs": [{"row_ref": rows[r], "option_text": v} for r, v in key.items()]}
    if k == "number":
        return {"text": str(key).replace(".", ",")}
    return {"text": key[0]}


def test_bank_is_consistent(bank):
    assert len(bank) >= 90
    cats = {it["cat"] for it in bank}
    assert {"general", "niche", "math", "tricky", "image", "match", "order", "injection"} <= cats
    assert {it["kind"] for it in bank} == set(qe.KINDS)


def test_bank_errors_detected():
    with pytest.raises(qe.BankError):
        qe.check_bank([{"id": "a", "cat": "c", "kind": "single", "text": "?", "options": ["x"], "answer": "y"}])
    with pytest.raises(qe.BankError):
        qe.check_bank([{"id": "a", "cat": "c", "kind": "order", "text": "?", "options": ["x", "y"],
                        "answer": ["x"]}])
    item = {"id": "a", "cat": "c", "kind": "number", "text": "?", "answer": 1}
    with pytest.raises(qe.BankError):
        qe.check_bank([item, dict(item)])


def test_perfect_answers_pass_solver_validation_and_grade(bank):
    """Эталон проходит validate решателя (форма вопроса верна) и засчитывается."""
    for i, item in enumerate(bank, 1):
        q = qe.to_question(item, i)
        ans = qs.validate(q, perfect(item, q))
        assert qe.grade(item, q, ans) == (True, 1.0), item["id"]


def test_prompt_builds_for_every_question(bank):
    for i, item in enumerate(bank, 1):
        q = qe.to_question(item, i)
        prompt = qs.build_prompt(q, has_crop=qs.needs_crop(q), short=False)
        assert item["text"][:30] in prompt


def test_wrong_and_partial_answers():
    item = {"id": "m", "cat": "c", "kind": "multi", "text": "?", "options": ["a", "b", "c"], "answer": ["a", "b"]}
    q = qe.to_question(item, 1)
    ok, score = qe.grade(item, q, {"refs": ["q1o0"]})
    assert not ok and score == pytest.approx(0.5)
    item = {"id": "o", "cat": "c", "kind": "order", "text": "?", "options": ["a", "b", "c"], "answer": ["a", "b", "c"]}
    q = qe.to_question(item, 1)
    ok, score = qe.grade(item, q, {"order": ["q1o0", "q1o2", "q1o1"]})
    assert not ok and score == pytest.approx(2 / 3)
    assert qe.grade(item, q, None) == (False, 0.0)


def test_number_parsing():
    assert qe.parse_number("0,25") == 0.25
    assert qe.parse_number("1/4") == 0.25
    assert qe.parse_number("−3") == -3
    assert qe.parse_number("28,26 см²") == pytest.approx(28.26)
    assert qe.parse_number("300 000 км/с") == 300000
    assert qe.parse_number("ответ: x = 6") == 6
    assert qe.parse_number("не знаю") is None
    item = {"kind": "number", "answer": 28.26, "tol": 0.1}
    assert qe.grade(item, {}, {"text": "28,3"})[0]
    assert not qe.grade({"kind": "number", "answer": 0.05, "tol": 0.001}, {}, {"text": "0,1"})[0]


def test_text_matching():
    exact = {"kind": "text", "answer": ["иена", "йена"]}
    assert qe.grade(exact, {}, {"text": "Иена."})[0]
    assert not qe.grade(exact, {}, {"text": "японская иена"})[0]
    contains = {"kind": "text", "answer": ["Толстой"], "match": "contains"}
    assert qe.grade(contains, {}, {"text": "Лев Николаевич Толстой"})[0]
    assert not qe.grade(contains, {}, {"text": "Толстоевский"})[0]
    assert qe.norm_text("«Ёлка»!") == "елка"


def test_crops_are_jpeg_for_every_question_that_needs_one(bank):
    from PIL import Image
    import io
    for i, item in enumerate(bank, 1):
        q = qe.to_question(item, i)
        if not qs.needs_crop(q):
            continue
        img = Image.open(io.BytesIO(qe.render_crop(item, q)))
        assert img.format == "JPEG" and img.width == 760, item["id"]
        if item.get("image"):
            assert img.height > 300


def test_run_with_fake_solver_counts_everything(bank):
    items = qe.select(bank, cats=["math", "match"])
    calls = []

    async def solve(q, crop, *, limiter=None, on_event=None, seconds_left=None):
        calls.append((q["index"], crop is not None))
        on_event("call", model="m", latency=1.5, ok=True, code="")
        item = items[q["index"] - 1]
        if item["id"] == "mat-11":
            return {"answer": {"text": "50"}, "model": "m", "tokens": 10}       # ловушка: неверно
        if item["id"] == "mat-15":
            raise RuntimeError("модель упала")
        return {"answer": perfect(item, q), "model": "m", "tokens": 10}

    results = run(qe.run(items, parallel=3, solve=solve))
    rep = qe.summarize(results, meta={"chain": ["m"], "parallel": 3, "crops": True}, wall=12.0)
    assert rep["n"] == len(items) == len(calls)
    assert rep["errors"] == 1
    assert rep["accuracy"] == pytest.approx((len(items) - 2) / len(items), abs=1e-3)
    assert {w["id"] for w in rep["wrong"]} == {"mat-11", "mat-15"}
    assert rep["call_seconds"]["p50"] == 1.5
    assert rep["by_cat"]["match"]["acc"] == 1.0
    assert all(crop for idx, crop in calls if items[idx - 1]["kind"] == "match")
    md = qe.to_markdown(rep)
    assert "Точность" in md and "mat-11" in md
    json.dumps(rep, ensure_ascii=False)                                        # сериализуется


def test_quota_wait_is_waited_then_retried():
    from sakura_core.llm import QuotaWait
    item = {"id": "n", "cat": "c", "kind": "number", "text": "?", "answer": 2}
    attempts, slept = [], []

    async def solve(q, crop, *, limiter=None, on_event=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise QuotaWait(7.0, "m")
        return {"answer": {"text": "2"}, "model": "m", "tokens": 1}

    async def sleep(s):
        slept.append(s)

    r = run(qe.solve_one(item, 1, crops=False, limiter=None, solve=solve, sleep=sleep))
    assert r.ok and slept == [7.0] and len(attempts) == 2

    async def always_wait(q, crop, *, limiter=None, on_event=None):
        raise QuotaWait(200.0, "m")

    r = run(qe.solve_one(item, 1, crops=False, limiter=None, solve=always_wait, sleep=sleep,
                         max_quota_wait=300))
    assert r.error == "quota_wait" and not r.ok


def test_compare_lists_fixed_and_broken(bank):
    items = qe.select(bank, ids=["gen-01", "gen-02"])
    a = qe.summarize([qe.Result("gen-01", "general", "single", ok=True, score=1),
                      qe.Result("gen-02", "general", "number")])
    b = qe.summarize([qe.Result("gen-01", "general", "single"),
                      qe.Result("gen-02", "general", "number", ok=True, score=1)])
    out = qe.compare(a, b)
    assert "Исправлено: gen-02" in out and "Сломано: gen-01" in out
    assert len(items) == 2


def test_cli_dry_run(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("quiz_eval_cli", qe.BANK_PATH.parents[2] / "scripts" / "quiz_eval.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path)
    assert cli.main(["--dry-run", "--cat", "image"]) == 0
    assert len(list((tmp_path / "crops").glob("*.jpg"))) == 7
    assert "Набор в порядке" in capsys.readouterr().out
