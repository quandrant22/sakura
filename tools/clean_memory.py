#!/usr/bin/env python3
"""
tools/clean_memory.py — очистка памяти Сакуры (CLI для Мастера).

Режимы:
  --scan            предпросмотр: что purge_intimate считает интимным (не удаляет)
  --purge           удалить интимные записи из master_memory + vec_master
  --find "слово"    поиск по подстроке (предпросмотр)
  --delete <id>     удалить одну запись по id
  --clean-history   вычистить интимный контент из history.json и session_summary
  --yes             не спрашивать подтверждение (для скриптов)

Перед любым удалением — автоматический бэкап БД в memory/sakura.db.bak-YYYYMMDD-HHMMSS
и JSON-источников в *.bak-<timestamp>.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.intimacy_mode import is_intimate_content  # noqa: E402
import memory.db as db  # noqa: E402


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backup_db() -> str:
    """Бэкап SQLite-БД (+WAL/SHM, если есть). Возвращает путь бэкапа."""
    src = db.DB_PATH
    dst = f"{src}.bak-{_ts()}"
    shutil.copy2(src, dst)
    for ext in ("-wal", "-shm"):
        if os.path.exists(src + ext):
            shutil.copy2(src + ext, dst + ext)
    print(f"[backup] {src} -> {dst}")
    return dst


def backup_json(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    dst = f"{path}.bak-{_ts()}"
    shutil.copy2(path, dst)
    print(f"[backup] {path} -> {dst}")
    return dst


def _print_rows(rows: list[dict], show_text: bool = True):
    if not rows:
        print("Ничего не найдено.")
        return
    print(f"Найдено: {len(rows)}")
    for r in rows:
        cats = r.get("category", "?")
        preview = (r.get("text", "")[:60] + "…") if show_text and r.get("text") else ""
        print(f"  #{r['id']:>5} [{cats}] {preview}")


def cmd_scan(args):
    rows = db.purge_intimate(dry_run=True)
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    print(f"[scan] Интимных записей в master_memory: {len(rows)}")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat}: {n}")
    if args.verbose:
        _print_rows(rows)


def cmd_purge(args):
    rows = db.purge_intimate(dry_run=True)
    if not rows:
        print("[purge] Интимных записей не найдено — удалять нечего.")
        return
    print(f"[purge] Найдено {len(rows)} записей для удаления.")
    _print_rows(rows, show_text=False)
    if not args.yes:
        ans = input("Удалить? (да/нет): ").strip().lower()
        if ans not in ("да", "y", "yes"):
            print("Отменено.")
            return
    backup_db()
    deleted = db.purge_intimate(dry_run=False)
    n = sum(1 for i in deleted if i["deleted"])
    print(f"[purge] Удалено {n} записей (из master_memory и vec_master).")


def cmd_find(args):
    rows = db.find_memories(args.find)
    _print_rows(rows)


def cmd_delete(args):
    backup_db()
    ok = db.delete_memory(int(args.delete))
    print(f"[delete] #{args.delete}: {'удалена' if ok else 'не найдена'}")


def _filter_history(history: list) -> tuple[list, int]:
    out, removed = [], 0
    for entry in history:
        parts = entry.get("parts", [])
        if any(is_intimate_content(p) for p in parts if isinstance(p, str)):
            removed += 1
            continue
        out.append(entry)
    return out, removed


def _filter_summary(data: dict) -> tuple[dict, int]:
    summary = data.get("summary", "")
    if summary and is_intimate_content(summary):
        data["summary"] = ""
        return data, 1
    return data, 0


def cmd_clean_history(args):
    """Интимный контент из history.json и session_summary."""
    import memory.memory as mem

    targets = [
        (mem.HISTORY_FILE, _filter_history),
        (mem.SESSION_FILE, _filter_summary),
    ]
    for path, filt in targets:
        if not os.path.exists(path):
            print(f"[history] {path}: нет файла — пропущено")
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        filtered, removed = filt(data)
        if removed:
            if not args.yes:
                print(f"[history] {path}: будет удалено записей — {removed}")
                ans = input("Удалить? (да/нет): ").strip().lower()
                if ans not in ("да", "y", "yes"):
                    print("Отменено.")
                    continue
            backup_json(path)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(filtered, f, ensure_ascii=False)
            print(f"[history] {path}: удалено {removed} записей с интимным контентом.")
        else:
            print(f"[history] {path}: интимного контента не найдено.")


def main():
    p = argparse.ArgumentParser(description="Очистка памяти Сакуры")
    p.add_argument("--scan", action="store_true", help="предпросмотр интимных записей")
    p.add_argument("--purge", action="store_true", help="удалить интимные записи")
    p.add_argument("--find", metavar="WORD", help="поиск по подстроке")
    p.add_argument("--delete", metavar="ID", help="удалить запись по id")
    p.add_argument("--clean-history", action="store_true",
                   help="очистить интимный контент из history.json и session_summary")
    p.add_argument("--yes", action="store_true", help="без подтверждения")
    p.add_argument("-v", "--verbose", action="store_true", help="показать текст записей")
    args = p.parse_args()

    if args.scan:
        cmd_scan(args)
    elif args.purge:
        cmd_purge(args)
    elif args.find is not None:
        cmd_find(args)
    elif args.delete is not None:
        cmd_delete(args)
    elif args.clean_history:
        cmd_clean_history(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()

