"""Точка входа: python -m desktop.core [--headless].

Фаза 0: только разбор аргументов; голосовой цикл и API подключаются в Фазе 1.
"""
import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="desktop.core", description="Sakura desktop core")
    ap.add_argument("--headless", action="store_true", help="без интерфейса, только ядро")
    ap.parse_args(argv)
    print("desktop.core: каркас (Фаза 0), сервисы ещё не подключены", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
