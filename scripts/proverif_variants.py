"""Сходящиеся варианты моделей ProVerif для CI (DECISIONS CV17, FINDINGS.md F1).

    python scripts/proverif_variants.py OUT_DIR

Полные модели ik.pv и xxpsk3.pv не завершаются за 50 минут (насыщение
расходится). Здесь из них механически, без правки исходников, строятся
варианты, которые сходятся:

    ik_core      — ik.pv без участника K (скомпрометированный сервер) и без
                   устройства атакующего D; запросы Q1–Q7, Q10 (Q8/Q9 — про K,
                   в ядре пусты).
    xxpsk3_auth  — xxpsk3.pv без weaksecret (Q7/Q8); процесс без изменений.

Каждое удаление сверяется с исходником: если строка не найдена (модель
изменилась), скрипт падает, а не строит молча другой вариант.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PV_DIR = ROOT / "docs" / "security" / "proverif"

QUERY_RE = re.compile(r"(?ms)^(?:query|weaksecret|noninterf) .*?\.[ \t]*$")

IK_DROP_LINES = [
    "  insert registry(exp(gen, skS), exp(gen, skD));\n",
    "  insert registry(exp(gen, skK), exp(gen, skC));\n",
    "    | (!Client(skC, exp(gen, skK), pub_c))\n",
    "    | (!Server(skK, pub_s))\n",
]

# вариант → (исходная модель, удаляемые строки процесса, оставляемые запросы по номеру Q)
VARIANTS: dict[str, tuple[str, list[str], list[int]]] = {
    "ik_core": ("ik.pv", IK_DROP_LINES, [1, 2, 3, 4, 5, 6, 7, 10]),
    "xxpsk3_auth": ("xxpsk3.pv", [], [1, 2, 3, 4, 5, 6, 9, 10]),
}


def queries(text: str) -> list[re.Match[str]]:
    head = text.split("\nlet ", 1)[0]
    return list(QUERY_RE.finditer(head))


def build(name: str) -> str:
    src, drop, keep = VARIANTS[name]
    text = (PV_DIR / src).read_text(encoding="utf-8")
    qs = queries(text)
    if len(qs) != 10:
        raise SystemExit(f"{src}: запросов {len(qs)}, ожидалось 10 — обновить VARIANTS")
    for i, m in reversed(list(enumerate(qs, 1))):
        if i not in keep:
            text = text[: m.start()] + f"(* Q{i} — вне варианта {name} *)" + text[m.end():]
    for line in drop:
        if text.count(line) != 1:
            raise SystemExit(f"{src}: строка не найдена ровно один раз: {line!r}")
        text = text.replace(line, "")
    banner = f"(* СГЕНЕРИРОВАНО scripts/proverif_variants.py из {src}: вариант {name}. Не править. *)\n"
    return banner + text


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    for name in VARIANTS:
        (out / f"{name}.pv").write_text(build(name), encoding="utf-8")
        print(out / f"{name}.pv")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
