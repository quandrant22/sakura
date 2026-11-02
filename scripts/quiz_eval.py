#!/usr/bin/env python3
"""Замер решателя тестов на эталонном наборе (eval/quiz/bank.json).

Запуск на VPS из папки Сакуры (ключ Gemini — тот же, что у Сакуры):

  venv/bin/python scripts/quiz_eval.py                    # весь набор, модели QUIZ_MODEL_CHAIN
  venv/bin/python scripts/quiz_eval.py --cat math,image   # только категории
  venv/bin/python scripts/quiz_eval.py --chain gemini-3.5-flash-lite --tag flashlite
  venv/bin/python scripts/quiz_eval.py --no-crops         # без кадров-вырезок
  venv/bin/python scripts/quiz_eval.py --dry-run          # без модели: проверка набора и кадры в папку
  venv/bin/python scripts/quiz_eval.py --compare A.json B.json

Отчёты: data/quiz_eval/<время>[-tag].json и .md. Квота считается отдельным
лимитером (не в data/gemma_quota.json): запускать, когда задачи браузера нет.
Тексты ответов модели в отчёте — данные набора, секретов там нет.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "quiz_eval"


def _args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bank", default=None, help="путь к набору (по умолчанию eval/quiz/bank.json)")
    p.add_argument("--cat", default="", help="категории через запятую")
    p.add_argument("--id", default="", help="id вопросов через запятую")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--chain", default="", help="модели решателя через запятую (по умолчанию QUIZ_MODEL_CHAIN)")
    p.add_argument("--parallel", type=int, default=0, help="одновременно (по умолчанию QUIZ_PARALLEL)")
    p.add_argument("--no-crops", action="store_true", help="решать только текстом")
    p.add_argument("--crop", choices=("media", "all"), default="",
                   help="правило кадров (по умолчанию QUIZ_CROP): media — только с картинкой, all — прежнее")
    p.add_argument("--temperature", type=float, default=None,
                   help="температура первой попытки (по умолчанию QUIZ_TEMPERATURE / модели)")
    p.add_argument("--max-tokens", type=int, default=0, help="потолок первой попытки (по умолчанию QUIZ_MAX_TOKENS)")
    p.add_argument("--tag", default="", help="метка в имени отчёта")
    p.add_argument("--dry-run", action="store_true", help="без модели: проверка набора, кадры в data/quiz_eval/crops")
    p.add_argument("--compare", nargs=2, metavar=("A", "B"))
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = _args(argv)
    from sakura_core import quiz_eval as qe

    if a.compare:
        ra, rb = (json.loads(Path(x).read_text(encoding="utf-8")) for x in a.compare)
        print(qe.compare(ra, rb))
        return 0

    items = qe.load_bank(a.bank or qe.BANK_PATH)
    items = qe.select(items, cats=[c for c in a.cat.split(",") if c] or None,
                      ids=[i for i in a.id.split(",") if i] or None, limit=a.limit)
    if not items:
        print("Нет вопросов под фильтр.")
        return 1

    if a.dry_run:
        from sakura_core.quiz_solver import needs_crop
        out = OUT_DIR / "crops"
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for i, it in enumerate(items, 1):
            q = qe.to_question(it, i)
            if needs_crop(q):
                (out / f"{it['id']}.jpg").write_bytes(qe.render_crop(it, q))
                n += 1
        print(f"Набор в порядке: {len(items)} вопросов. Кадров: {n} → {out}")
        if not qe.has_cyrillic_font():
            print("Внимание: шрифт DejaVuSans не найден — кириллица на кадрах будет квадратами "
                  "(apt-get install fonts-dejavu-core).")
        return 0

    import config
    if a.chain:
        config.QUIZ_MODEL_CHAIN = tuple(m.strip() for m in a.chain.split(",") if m.strip())
    if a.crop:
        config.QUIZ_CROP = a.crop
    if a.max_tokens:
        config.QUIZ_MAX_TOKENS = a.max_tokens
    if a.temperature is not None:
        config.QUIZ_TEMPERATURE = a.temperature
    parallel = a.parallel or config.QUIZ_PARALLEL
    meta = {"started": datetime.now().strftime("%Y-%m-%d %H:%M"), "chain": list(config.QUIZ_MODEL_CHAIN),
            "parallel": parallel, "crops": not a.no_crops, "crop_rule": config.QUIZ_CROP,
            "temperature": config.QUIZ_TEMPERATURE, "max_tokens": config.QUIZ_MAX_TOKENS, "bank": str(a.bank or qe.BANK_PATH),
            "tag": a.tag}
    print(f"Вопросов {len(items)}, модели {', '.join(meta['chain'])}, параллельно {parallel}, "
          f"кадры {'да' if meta['crops'] else 'нет'}")

    def progress(done, total, r):
        mark = "✓" if r.ok else ("!" if r.error else "✗")
        extra = f"  попыток {len(r.attempts)}" + (f", ждал {r.wait_seconds:.0f} с" if r.wait_seconds else "") \
            + (f", ошибки {','.join(r.call_errors)}" if r.call_errors else "")
        print(f"  [{done:>3}/{total}] {mark} {r.id:<8} {r.seconds:>6.1f} с  {r.model or r.error}{extra}", flush=True)

    t0 = time.monotonic()
    results = asyncio.run(qe.run(items, parallel=parallel, crops=not a.no_crops, progress=progress))
    rep = qe.summarize(results, meta=meta, wall=time.monotonic() - t0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = datetime.now().strftime("%Y%m%d-%H%M") + (f"-{a.tag}" if a.tag else "")
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    md = qe.to_markdown(rep)
    (OUT_DIR / f"{stem}.md").write_text(md, encoding="utf-8")
    print()
    print(md)
    print(f"Отчёт: {OUT_DIR / stem}.json / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
