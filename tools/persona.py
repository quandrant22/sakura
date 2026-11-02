"""tools/persona.py — образ Сакуры из консоли сервера.

    python3 tools/persona.py                       # обзор
    python3 tools/persona.py show intimate         # печать образа
    python3 tools/persona.py set intimate file.md  # перезаписать из файла
    python3 tools/persona.py reset intimate        # вернуть заводской
    python3 tools/persona.py undo intimate         # предыдущая версия

Пишет в то же единственное хранилище, что и /образ в Telegram
(sakura_core/persona, каталог memory/persona/). Перезапуск не нужен.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sakura_core import persona


def main(argv: list[str]) -> int:
    if not argv:
        for mode in persona.MODES:
            print(f"{mode:9} {persona.origin(mode):8} {len(persona.get(mode)):6} симв.  "
                  f"история: {len(persona.history(mode))}")
        return 0
    cmd, *rest = argv
    if cmd == "show" and len(rest) == 1:
        print(persona.get(rest[0]))
        return 0
    if cmd == "set" and len(rest) == 2:
        persona.set(rest[0], Path(rest[1]).read_text(encoding="utf-8"), source="cli")
        print(f"{rest[0]}: перезаписан")
        return 0
    if cmd == "reset" and len(rest) == 1:
        persona.reset(rest[0], source="cli")
        print(f"{rest[0]}: заводской")
        return 0
    if cmd == "undo" and len(rest) == 1:
        print(f"{rest[0]}: " + ("откатан" if persona.rollback(rest[0], source="cli") else "истории нет"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except persona.PersonaError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        sys.exit(1)
