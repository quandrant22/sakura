#!/usr/bin/env python3
"""Очистка накопившегося мусора: memory/tasks.json и открытые нити разговора.

  python scripts/cleanup_tasks.py --dry-run   # только показать (кол-во и первые 40 символов)
  python scripts/cleanup_tasks.py             # копия в memory/backup/<дата>/ → очистка

Запускать из корня проекта тем же python, что и сервер. Сначала --dry-run.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="ничего не менять, только показать")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from modules import task_cleanup

    pv = task_cleanup.preview()
    print(f"Задач: {len(pv['tasks'])}")
    for t in pv["tasks"]:
        print(f"  - {t}")
    print(f"Открытых нитей: {len(pv['threads'])}")
    for t in pv["threads"]:
        print(f"  - {t}")
    if args.dry_run:
        print("--dry-run: ничего не изменено.")
        return 0
    res = task_cleanup.run()
    print(f"Резервная копия: {res['backup']}")
    print(f"Удалено задач: {res['tasks']}, закрыто нитей: {res['threads']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
