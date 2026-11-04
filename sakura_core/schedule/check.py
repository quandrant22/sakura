"""Живая проверка источника расписания на VPS (без записи в хранилище).

  cd /opt/sakura && venv/bin/python -m sakura_core.schedule.check [eios|direct]

Печатает статус, число занятий и даты — без логина, пароля и ФИО.
"""
from __future__ import annotations

import asyncio
import sys


async def _run(source: str) -> int:
    import config
    from sakura_core.schedule.eios import AuthError, EiosClient
    from sakura_core.schedule.fetch import Blocked, FetchError, fetch_direct
    from sakura_core.schedule.parse import ParseError, parse_eios, parse_ttable

    if source == "eios":
        client = EiosClient()
        try:
            got = await client.fetch()
        finally:
            await client.aclose()
    else:
        got = await fetch_direct()

    if isinstance(got, Blocked):
        print(f"{source}: ЗАЩИТА — сервер получает страницу проверки, данных нет")
        return 2
    if isinstance(got, AuthError):
        print(f"{source}: ВХОД НЕ УДАЛСЯ — проверь EIOS_USERNAME и EIOS_PASSWORD в .env")
        return 3
    if isinstance(got, FetchError):
        print(f"{source}: ОШИБКА — {got.reason}")
        return 4
    try:
        lessons = (parse_eios(got.ttable, config.MUIV_GROUP) if source == "eios"
                   else parse_ttable(got.ttable))
    except ParseError as e:
        print(f"{source}: СТРАНИЦА НЕ РАЗОБРАНА — {e}")
        return 5
    days = sorted({x.date.strftime("%d.%m") for x in lessons})
    print(f"{source}: OK — занятий {len(lessons)}, дни: {', '.join(days) or 'нет'}")
    return 0


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "eios"
    if source not in ("eios", "direct"):
        print("использование: python -m sakura_core.schedule.check [eios|direct]")
        return 1
    return asyncio.run(_run(source))


if __name__ == "__main__":
    sys.exit(main())
