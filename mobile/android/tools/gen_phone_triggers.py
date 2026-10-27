"""Генератор app/src/main/assets/phone_triggers.json из реестра способностей.

    py -3.11 mobile/android/tools/gen_phone_triggers.py

Источник phone.*: sakura_core/capabilities.yaml (только чтение). Пока сервер без phone.*
(DECISIONS D29) — tools/phone_triggers.seed.yaml. Остальные действия реестра попадают в список
"actions" для конструктора сценариев (id, desc, params) без триггеров.

PyYAML не используется (в tools/.venv только пакеты securechannel/): формат реестра узкий —
элементы списка `- id:`, поля `desc: '...'`, `triggers: [...]` (литерал Python), `params:` со
строками `- name: x`.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REGISTRY = ROOT / "sakura_core" / "capabilities.yaml"
SEED = HERE / "phone_triggers.seed.yaml"
OUT = HERE.parent / "app" / "src" / "main" / "assets" / "phone_triggers.json"


def parse(text: str) -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    in_params = False
    lines: list[str] = []
    pending = ""
    for raw in text.splitlines():           # склейка многострочных [...]
        if pending:
            pending += " " + raw.strip()
            if pending.count("[") <= pending.count("]"):
                lines.append(pending)
                pending = ""
            continue
        if re.match(r"^  \w+:\s*\[", raw) and raw.count("[") > raw.count("]"):
            pending = raw.rstrip()
            continue
        lines.append(raw)
    for raw in lines:
        line = raw.split("  #")[0].rstrip() if "  #" in raw else raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^- id:\s*(\S+)", line)
        if m:
            cur = {"id": m.group(1), "desc": "", "params": [], "triggers": []}
            items.append(cur)
            in_params = False
            continue
        if cur is None:
            continue
        m = re.match(r"^  (\w+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            in_params = key == "params" and not val
            if key == "desc":
                cur["desc"] = ast.literal_eval(val) if val[:1] in "'\"" else val
            elif key == "triggers":
                cur["triggers"] = list(ast.literal_eval(val))
            elif key == "params" and val.startswith("["):
                cur["params"] = [p for p in ast.literal_eval(val)]
            continue
        m = re.match(r"^\s+-\s*name:\s*(\S+)", line)
        if m and in_params:
            cur["params"].append(m.group(1))
    return items


def main() -> None:
    registry = parse(REGISTRY.read_text(encoding="utf-8"))
    phone = [a for a in registry if a["id"].startswith("phone.")]
    source = "sakura_core/capabilities.yaml"
    if not phone:
        phone = parse(SEED.read_text(encoding="utf-8"))
        source = "mobile/android/tools/phone_triggers.seed.yaml (сервер ещё без phone.*)"
    triggers = []
    for a in phone:
        for t in a["triggers"]:
            triggers.append({"trigger": t.lower().replace("ё", "е"), "action": a["id"]})
    triggers.sort(key=lambda x: (-len(x["trigger"]), x["trigger"]))   # самый длинный — первым
    actions = [{"id": a["id"], "desc": a["desc"], "params": a["params"]}
               for a in sorted(registry + [p for p in phone if p not in registry], key=lambda a: a["id"])]
    data = {"generator": "mobile/android/tools/gen_phone_triggers.py", "phone_source": source,
            "triggers": triggers, "actions": actions}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"phone.*: {len(phone)} ({source}); триггеров {len(triggers)}; действий реестра {len(actions)}")


if __name__ == "__main__":
    main()
