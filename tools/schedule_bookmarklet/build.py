"""Сборка букмарклета «Сакура: расписание».

  SCHEDULE_PUSH_URL=https://<домен>/schedule/push \
  SCHEDULE_PUSH_TOKEN=<токен из .env> \
  python tools/schedule_bookmarklet/build.py > /dev/clipboard   # или в файл вне репозитория

Печатает строку javascript:… в stdout — её вставляют в адрес закладки.
Строка содержит токен: в git, чаты и логи её не класть. Группа — те же
значения, что MUIV_* в config.py (сверяет тест test_schedule_bookmarklet).
Можно переопределить переменными окружения MUIV_*.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

SRC = Path(__file__).with_name("bookmarklet.js")

DEFAULT_FORM = {
    "el": "groupnames",
    "branch": "gv",
    "year": "Курс 2",
    "faculty": "Информационных технологий",
    "studyform": "Очная",
    "groupname": "ИД 86.1/М1-25",
    "edulevel": "",
}
_ENV = {"branch": "MUIV_BRANCH", "year": "MUIV_YEAR", "faculty": "MUIV_FACULTY",
        "studyform": "MUIV_STUDYFORM", "groupname": "MUIV_GROUP"}


def form_from_env(env=os.environ) -> dict[str, str]:
    form = dict(DEFAULT_FORM)
    for key, var in _ENV.items():
        if env.get(var):
            form[key] = env[var]
    return form


def build(endpoint: str, token: str, form: dict[str, str]) -> str:
    if not endpoint.startswith("https://"):
        raise ValueError("SCHEDULE_PUSH_URL должен начинаться с https://")
    if not token:
        raise ValueError("нет SCHEDULE_PUSH_TOKEN")
    js = SRC.read_text(encoding="utf-8")
    js = "\n".join(line for line in js.splitlines() if not line.strip().startswith("//"))
    js = (js.replace("__ENDPOINT__", json.dumps(endpoint))
            .replace("__TOKEN__", json.dumps(token))
            .replace("__FORM__", json.dumps(form, ensure_ascii=False)))
    js = re.sub(r"\s*\n\s*", " ", js).strip()
    return "javascript:" + quote(js, safe="")


def main() -> int:
    try:
        out = build(os.environ.get("SCHEDULE_PUSH_URL", ""),
                    os.environ.get("SCHEDULE_PUSH_TOKEN", ""), form_from_env())
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    print("Внимание: строка ниже содержит токен — не коммить и не пересылай.", file=sys.stderr)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
