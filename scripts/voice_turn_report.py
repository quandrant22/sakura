"""p50/p90 этапов голосового хода по строкам [turn] журнала (perf/voice-2).

    journalctl -u sakura --since today | python scripts/voice_turn_report.py
    journalctl -u sakura --since today | python scripts/voice_turn_report.py --last 20

Читает только строки [turn] (тайминги, без текстов запросов и ответов).
"""

import argparse
import re
import sys
from collections import defaultdict

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))

_LINE = re.compile(r"\[turn\] (?P<id>[0-9a-f]{12}) dev=\S+ kind=(?P<kind>\w+)(?P<rest>.*) мс")
_MARK = re.compile(r"(\w+)=(\d+)")


def parse(lines):
    for line in lines:
        m = _LINE.search(line)
        if not m or " cancelled" in m["rest"]:
            continue
        marks = {k: float(v) for k, v in _MARK.findall(m["rest"])}
        flags = [w for w in m["rest"].split() if "=" not in w]
        yield m["kind"], marks, flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=0, help="последние N ходов каждого вида")
    args = ap.parse_args()
    from sakura_core.turn_timing import summary
    rows = list(parse(sys.stdin))
    by_kind = defaultdict(list)
    for kind, marks, flags in rows:
        by_kind[kind].append((marks, flags))
    samples = []
    for kind, items in by_kind.items():
        items = items[-args.last:] if args.last else items
        samples += [(kind, marks) for marks, _ in items]
        early = sum("early_gate" in f for _, f in items)
        late = sum("verdict_after_audio" in f for _, f in items)
        if early:
            print(f"{kind}: ранний шлюз {early} из {len(items)}, "
                  f"«команда» после первого звука: {late}")
    for line in summary(samples):
        print(line)


if __name__ == "__main__":
    main()
