"""Золотой набор «мозгов» Сакуры: правила по regex + судья-LLM по рубрике.

Сценарии — tests/golden/*.yaml (категории, реплика Мастера, история,
ожидание, правила). Режимы:

  --offline  поддельный LLM: проверяет сборку промпта (персона, блоки без
             счётчиков) и движок правил на эталонных/плохих примерах. Сети нет.
  --online   реальные ответы (цепочка voice/chat как в бою) и оценка
             судьёй (цепочка background). Лимит запросов — --max-requests.

  python tools/brain_eval.py --offline [--persona current|v2]
  python tools/brain_eval.py --online --persona v2 --data-dir /tmp/copy \\
         --keys-from /opt/sakura --max-requests 150 --out /tmp/eval_v2.jsonl

--data-dir — КОПИЯ каталога данных (memory/*, sakura.db): сборка промпта
обновляет счётчики памяти, боевой каталог трогать нельзя. --keys-from —
каталог, из которого код один раз берёт активный ключ (сам ключ не
печатается); дальше процесс работает в --data-dir.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "tests" / "golden"
V2_FILE = ROOT / "docs" / "brain" / "persona_v2_draft.md"

# ── правила ─────────────────────────────────────────────────────────

BASE_RULES = {"no_counters": True, "no_flat_voice": True, "lang_ru": True,
              "vy_form": True, "no_markdown": True, "no_emoji": True}

_COUNTER = re.compile(r"\d+\s*(дн|час|недел|месяц|мин|раз)", re.I)
_TY = re.compile(r"\b(ты|тебя|тебе|тобой|твой|твоя|твоё|твои|сделаешь|хочешь|можешь|знаешь|"
                 r"думаешь|собираешься)\b", re.I)
_MD = re.compile(r"\*\*|^#{1,6}\s|^\s*[-*]\s|`", re.M)
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
_SENT = re.compile(r"(?<=[.!?…])\s+")


def sentences(text: str) -> int:
    return len([s for s in _SENT.split(text.strip()) if s.strip()])


def check_rules(answer: str, rules: dict) -> list[str]:
    """Нарушения правил: список «имя: подробность». Пусто — всё прошло."""
    a = answer or ""
    bad = []
    if not a.strip():
        return ["empty: пустой ответ"]
    if rules.get("no_counters") and _COUNTER.search(a):
        bad.append(f"no_counters: {_COUNTER.search(a).group(0)}")
    if rules.get("no_flat_voice") and "ровным голосом" in a.lower():
        bad.append("no_flat_voice")
    if rules.get("lang_ru"):
        cyr = len(re.findall(r"[а-яё]", a, re.I))
        lat = len(re.findall(r"[a-z]", a, re.I))
        if cyr < max(3, lat):
            bad.append("lang_ru: мало кириллицы")
    if rules.get("vy_form") and _TY.search(a):
        bad.append(f"vy_form: «{_TY.search(a).group(0)}»")
    if rules.get("no_markdown") and _MD.search(a):
        bad.append("no_markdown")
    if rules.get("no_emoji") and _EMOJI.search(a):
        bad.append("no_emoji")
    if rules.get("max_sentences") and sentences(a) > rules["max_sentences"]:
        bad.append(f"max_sentences: {sentences(a)} > {rules['max_sentences']}")
    if rules.get("no_question_end") and a.rstrip().endswith("?"):
        bad.append("no_question_end")
    if rules.get("no_exclaim") and "!" in a:
        bad.append("no_exclaim")
    for rx in rules.get("must_not", []):
        if re.search(rx, a, re.I | re.M):
            bad.append(f"must_not: {rx}")
    for rx in rules.get("must", []):
        if not re.search(rx, a, re.I | re.M):
            bad.append(f"must: {rx}")
    return bad


# ── сценарии ────────────────────────────────────────────────────────


def load_scenarios() -> list[dict]:
    import yaml
    out = []
    for path in sorted(glob.glob(str(GOLDEN / "*.yaml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8"))
        d = doc.get("defaults", {})
        for s in doc["scenarios"]:
            rules = {**BASE_RULES, **d.get("rules", {}), **s.get("rules", {})}
            if "must_not" in d.get("rules", {}) and "must_not" in s.get("rules", {}):
                rules["must_not"] = d["rules"]["must_not"] + s["rules"]["must_not"]
            out.append({"id": s["id"], "category": doc["category"],
                        "channel": s.get("channel", d.get("channel", "chat")),
                        "user": s["user"], "history": s.get("history", []),
                        "expect": s.get("expect", ""), "rules": rules,
                        "file": os.path.basename(path)})
    return out


def persona_v2_text() -> str:
    md = V2_FILE.read_text(encoding="utf-8")
    m = re.search(r"## Текст персоны v2\s+```text\n(.*?)```", md, re.S)
    if not m:
        raise SystemExit("не найден блок персоны v2 в " + str(V2_FILE))
    return m.group(1).strip()


# ── офлайн ──────────────────────────────────────────────────────────

# Эталоны движка правил: (ответ, правило, должно ли нарушаться)
SELF_TEST = [
    ("Запускаю.", {"max_sentences": 1}, False),
    ("Мы вместе уже 116 дней.", {"no_counters": True}, True),
    ("Озвучь текст ниже ровным голосом.", {"no_flat_voice": True}, True),
    ("Ты серьёзно?", {"vy_form": True}, True),
    ("Вы серьёзно.", {"vy_form": True}, False),
    ("**Среда**\n* урок", {"no_markdown": True}, True),
    ("Готово. Что-то ещё?", {"no_question_end": True}, True),
    ("Конечно! Сейчас!", {"no_exclaim": True}, True),
    ("Молоко.", {"must": ["молок"]}, False),
]


def offline(persona: str) -> int:
    from personality import get_system_prompt
    text = persona_v2_text() if persona == "v2" else get_system_prompt()
    problems = []
    if "ровным голосом" in text:
        problems.append("персона содержит «ровным голосом»")
    if "Не называй счётчики и сроки" not in text:
        problems.append("в персоне нет правила про счётчики и сроки")
    if _COUNTER.search(text):
        problems.append(f"в персоне число со сроком: {_COUNTER.search(text).group(0)}")
    print(f"[offline] персона {persona}: {len(text)} симв (~{round(len(text) / 3.5)} ток); "
          f"проблем: {len(problems)}")
    for p in problems:
        print("   -", p)
    fails = 0
    for answer, rules, should_fail in SELF_TEST:
        got = bool(check_rules(answer, rules))
        if got != should_fail:
            fails += 1
            print(f"   ✗ движок правил: {answer!r} {rules} → {got}, ожидалось {should_fail}")
    scen = load_scenarios()
    cats = {}
    for s in scen:
        cats.setdefault(s["category"], 0)
        cats[s["category"]] += 1
        # поддельный LLM: эталонный короткий ответ должен проходить базовые правила
        fake = "Готово." if s["category"] == "команды" else "Не помню, Мастер. Выдумывать не стану."
        if check_rules(fake, {k: v for k, v in s["rules"].items() if k not in ("must",)}):
            fails += 1
            print(f"   ✗ {s['id']}: эталонный ответ не проходит правила {check_rules(fake, s['rules'])}")
    print(f"[offline] сценариев {len(scen)}: " + ", ".join(f"{k} {v}" for k, v in cats.items()))
    print(f"[offline] итог: {'OK' if not (fails or problems) else 'ОШИБКИ'} "
          f"(движок/сценарии {fails}, персона {len(problems)})")
    return 1 if fails or problems else 0


# ── онлайн ──────────────────────────────────────────────────────────

JUDGE = """Ты оцениваешь ответ голосовой помощницы-дворецкой Сакуры её хозяину (Мастеру).
Идеал: коротко, точно, сухой юмор без развёрнутых острот, на «вы», статус-отчёт на команды,
без выдуманных фактов, без поучений, по-русски.

Канал: {channel}. Реплика Мастера: «{user}»
Что ожидается: {expect}
Ответ Сакуры: «{answer}»

Оцени по шкале 1–5: character (характер), factuality (не выдумывает, честна),
brevity (краткость к месту), usefulness (польза). Ответь ТОЛЬКО JSON:
{{"character": n, "factuality": n, "brevity": n, "usefulness": n, "comment": "до 20 слов"}}"""


class Budget:
    def __init__(self, limit: int):
        self.limit, self.used = limit, 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


async def online(args) -> int:
    os.chdir(args.keys_from)
    # Настройки сервиса (как при запуске боевого config); значения не печатаются.
    from dotenv import load_dotenv
    load_dotenv(os.path.join(args.keys_from, ".env"))
    import config
    key = config.get_active_key()
    if not key:
        raise SystemExit("нет активного ключа")
    os.chdir(args.data_dir)                  # дальше — только копия данных
    config.get_active_key = lambda: key
    config.mark_key_used = lambda k: None
    if hasattr(config, "mark_key_exhausted"):
        config.mark_key_exhausted = lambda k: None
    from google.genai import types as T
    import sakura_core.llm as llm
    import sakura_core.prompt as P
    from sakura_core.llm import _LEN_HINT
    if args.persona == "v2":
        v2 = persona_v2_text()
        P.get_system_prompt = lambda *a, **k: v2
    budget = Budget(args.max_requests)
    scen = load_scenarios()
    if args.only:
        scen = [s for s in scen if re.search(args.only, s["id"])]
    out = open(args.out, "w", encoding="utf-8")
    for s in scen:
        if not budget.take():
            print("лимит запросов исчерпан", flush=True)
            break
        system = await P._build_system(query=s["user"] if s["channel"] == "voice" else "")
        if s["channel"] == "voice":
            system += "\n\n" + _LEN_HINT["short"]
        contents = [T.Content(role=h["role"], parts=[T.Part(text=h["text"])]) for h in s["history"]]
        contents.append(T.Content(role="user", parts=[T.Part(text=s["user"])]))
        chain = config.VOICE_MODEL_CHAIN if s["channel"] == "voice" else config.MODEL_CHAIN
        t0 = time.monotonic()
        answer = (await llm.generate(contents, system=system, chain=chain, api_key=key,
                                     max_tokens=120 if s["channel"] == "voice" else 800)).strip()
        answer = llm.clean_reply(answer) if hasattr(llm, "clean_reply") else answer
        dt = time.monotonic() - t0
        bad = check_rules(answer, s["rules"])
        judge = None
        if answer and budget.take():
            raw = await llm.generate(
                [T.Content(role="user", parts=[T.Part(text=JUDGE.format(
                    channel=s["channel"], user=s["user"], expect=s["expect"], answer=answer))])],
                chain=config.BACKGROUND_MODEL_CHAIN, api_key=key, temperature=0.0,
                max_tokens=200, response_mime_type="application/json")
            try:
                judge = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            except Exception:
                judge = {"error": (raw or "")[:120]}
        row = {"id": s["id"], "category": s["category"], "persona": args.persona,
               "channel": s["channel"], "user": s["user"], "answer": answer,
               "llm_s": round(dt, 2), "system_chars": len(system),
               "rule_fail": bad, "judge": judge}
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
        print(f"{s['id']} | {'OK' if not bad else 'FAIL ' + '; '.join(bad)} | {judge} | {answer[:90]}",
              flush=True)
        await asyncio.sleep(args.pause)
    out.close()
    print(f"запросов использовано: {budget.used}", flush=True)
    return 0


def summarize(paths: list[str]) -> None:
    """Таблица по категориям для одного или нескольких jsonl (по персонам)."""
    import statistics as st
    rows = [json.loads(l) for p in paths for l in open(p, encoding="utf-8")]
    print("персона | категория | n | правила OK | характер | факты | краткость | польза")
    keyf = lambda r: (r["persona"], r["category"])
    for (persona, cat) in sorted({keyf(r) for r in rows}):
        rs = [r for r in rows if keyf(r) == (persona, cat)]
        ok = sum(1 for r in rs if not r["rule_fail"])
        js = [r["judge"] for r in rs if isinstance(r.get("judge"), dict) and "character" in r["judge"]]
        m = lambda k: f"{st.mean(j[k] for j in js):.1f}" if js else "—"
        print(f"{persona} | {cat} | {len(rs)} | {ok}/{len(rs)} | {m('character')} | {m('factuality')} | "
              f"{m('brevity')} | {m('usefulness')}")
    for persona in sorted({r["persona"] for r in rows}):
        rs = [r for r in rows if r["persona"] == persona]
        js = [r["judge"] for r in rs if isinstance(r.get("judge"), dict) and "character" in r["judge"]]
        tot = lambda k: st.mean(j[k] for j in js) if js else 0
        print(f"ИТОГО {persona}: правила {sum(1 for r in rs if not r['rule_fail'])}/{len(rs)}, "
              f"характер {tot('character'):.2f}, факты {tot('factuality'):.2f}, "
              f"краткость {tot('brevity'):.2f}, польза {tot('usefulness'):.2f}, "
              f"system ср {st.mean(r['system_chars'] for r in rs):.0f} симв")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--online", action="store_true")
    mode.add_argument("--summary", nargs="+", metavar="JSONL")
    ap.add_argument("--persona", choices=("current", "v2"), default="current")
    ap.add_argument("--data-dir")
    ap.add_argument("--keys-from", default="/opt/sakura")
    ap.add_argument("--max-requests", type=int, default=150)
    ap.add_argument("--pause", type=float, default=1.0)
    ap.add_argument("--only", help="regex по id сценария")
    ap.add_argument("--out", default="brain_eval.jsonl")
    args = ap.parse_args()
    if args.summary:
        summarize(args.summary)
        return 0
    if args.offline:
        return offline(args.persona)
    if not args.data_dir or os.path.realpath(args.data_dir) == os.path.realpath(args.keys_from):
        raise SystemExit("--online требует --data-dir с КОПИЕЙ данных (не боевой каталог)")
    return asyncio.run(online(args))


if __name__ == "__main__":
    sys.exit(main())
