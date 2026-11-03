"""Сверка сырого вывода ProVerif с ожиданиями (docs/security/proverif/expected.json).

    python scripts/check_proverif.py                 # таблица, код 1 при расхождении
    python scripts/check_proverif.py --update-formal # + столбец «фактический» в FORMAL.md §0

Вход — results/<модель>.txt без правок (README в results/). Обычные запросы
сопоставляются со строками RESULT по порядку объявления, weaksecret — по имени.
Расхождение не исправляется здесь и не правит модель: оно идёт в FINDINGS.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PV_DIR = ROOT / "docs" / "security" / "proverif"
FORMAL = ROOT / "docs" / "security" / "FORMAL.md"
FORMAL_PREFIX = {"ik_core": "ik", "xxpsk3_auth": "xx"}   # варианты (proverif_variants.py)
PENDING = "ожидает запуска"

RESULT_RE = re.compile(r"^RESULT (?P<what>.*) (?:is (?P<v>true|false)|(?P<cp>cannot be proved))\.\s*$")
WEAK_RE = re.compile(r"^Weak secret (?P<name>\S+)$")


@dataclass
class Row:
    model: str
    qid: str
    expect: str
    actual: str          # true | false | cannot be proved | нет вывода

    @property
    def ok(self) -> bool:
        return self.actual == self.expect


def parse_results(text: str) -> tuple[list[str], dict[str, str]]:
    """Строки RESULT → (обычные запросы по порядку, weaksecret по имени)."""
    plain: list[str] = []
    weak: dict[str, str] = {}
    for line in text.splitlines():
        m = RESULT_RE.match(line.strip())
        if not m:
            continue
        value = m["v"] or "cannot be proved"
        w = WEAK_RE.match(m["what"])
        if w:
            weak[w["name"]] = value
        else:
            plain.append(value)
    return plain, weak


def compare(model: str, expected: list[dict], text: str | None) -> tuple[list[Row], list[str]]:
    problems: list[str] = []
    if text is None:
        return [Row(model, e["id"], e["expect"], "нет вывода") for e in expected], [f"{model}: нет results/{model}.txt"]
    plain, weak = parse_results(text)
    want_plain = [e for e in expected if "weaksecret" not in e]
    if len(plain) != len(want_plain):
        problems.append(f"{model}: RESULT обычных запросов {len(plain)}, ожидалось {len(want_plain)} "
                        "(незавершение, ошибка разбора или иная группировка запросов)")
    rows: list[Row] = []
    it = iter(plain)
    for e in expected:
        if "weaksecret" in e:
            actual = weak.get(e["weaksecret"], "нет вывода")
        else:
            actual = next(it, "нет вывода")
        rows.append(Row(model, e["id"], e["expect"], actual))
    problems += [f"{r.model} {r.qid}: ожидалось {r.expect}, получено {r.actual}" for r in rows if not r.ok]
    return rows, problems


def update_formal(text: str, rows: list[Row]) -> str:
    """Последний столбец строк «| ik Qn |» / «| xx Qn |» таблицы §0."""
    by_key = {f"{FORMAL_PREFIX[r.model]} {r.qid}": r for r in rows}
    out = []
    for line in text.splitlines(keepends=True):
        m = re.match(r"^\| (ik|xx) (Q\d+) \|", line)
        row = by_key.get(f"{m[1]} {m[2]}") if m else None
        if row:
            body = line.rstrip("\n")
            cells = body.split("|")
            mark = "совпало" if row.ok else "**РАСХОЖДЕНИЕ** → FINDINGS.md"
            cells[-2] = f" {row.actual} ({mark}) "
            line = "|".join(cells) + ("\n" if line.endswith("\n") else "")
        out.append(line)
    return "".join(out)


def table(rows: list[Row]) -> str:
    lines = ["| модель | запрос | ожидаемый | фактический | |", "|---|---|---|---|---|"]
    lines += [f"| {r.model} | {r.qid} | {r.expect} | {r.actual} | {'ok' if r.ok else 'РАСХОЖДЕНИЕ'} |" for r in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=PV_DIR / "results")
    ap.add_argument("--expected", type=Path, default=PV_DIR / "expected.json")
    ap.add_argument("--update-formal", action="store_true")
    args = ap.parse_args(argv)

    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    rows: list[Row] = []
    problems: list[str] = []
    for model, exp in expected.items():
        if model.startswith("_"):
            continue
        path = args.results / f"{model}.txt"
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        r, p = compare(model, exp, text)
        rows += r
        problems += p

    print(table(rows))
    if args.update_formal:
        FORMAL.write_text(update_formal(FORMAL.read_text(encoding="utf-8"), rows), encoding="utf-8")
    if problems:
        print("\nРасхождения:", *problems, sep="\n- ")
        return 1
    print("\nВсе результаты совпали с ожидаемыми.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
