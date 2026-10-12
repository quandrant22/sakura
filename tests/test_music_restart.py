"""fix/music-restart: «трек сначала» (music.restart) отдельно от «предыдущий трек».

Таблица фраз → действие (реестр, без LLM) и golden-набор: снимок
маршрутизации реестра до правки (tests/fixtures/registry_golden.json —
все триггеры всех действий, они же с «Сакура, …» и «… пожалуйста», плюс
разговорные фразы, в четырёх контекстах). Текущий реестр обязан совпасть
со снимком везде, кроме явно перечисленных изменений.

Run: python -m pytest tests/test_music_restart.py -q
Пересобрать снимок (после намеренной правки реестра):
    python tests/test_music_restart.py sakura_core/capabilities.yaml
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sakura_core.registry import build_index, declaration_from_dict, load  # noqa: E402

GOLDEN = Path(__file__).parent / "fixtures" / "registry_golden.json"
CONTEXTS = (None, "playing:music", "window:browser", "window:youtube")
CHAT = (
    "как дела", "что нового у тебя", "расскажи анекдот", "давай поговорим",
    "давай начнём заново", "начни игру заново", "расскажи с начала",
    "объясни заново", "сначала открой браузер", "я устал сегодня",
    "какая погода завтра", "спокойной ночи", "что ты думаешь о музыке",
    "верни мне настроение", "включи что-нибудь весёлое", "повтори что ты сказала",
)


def _decls(yaml_path=None):
    if yaml_path is None:
        return load()
    raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    return [declaration_from_dict(r) for r in raw]


def golden_phrases(decls) -> list[str]:
    out = set(CHAT)
    for d in decls:
        for t in d.triggers:
            out |= {t, f"сакура, {t}", f"{t} пожалуйста"}
    return sorted(out)


def snapshot(decls, phrases) -> dict[str, str | None]:
    idx = build_index(decls)
    snap = {}
    for p in phrases:
        for c in CONTEXTS:
            m = idx.match(p, c)
            snap[f"{p} | {c or '-'}"] = m[1].id if m else None
    return snap


@pytest.fixture(scope="module")
def index():
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    return build_index(load())


# ── таблица фраз ───────────────────────────────────────────────────

RESTART = ["трек сначала", "включи сначала", "с начала", "заново",
           "перезапусти трек", "начни трек заново",
           "Сакура, включи трек сначала", "давай этот трек заново",
           "поставь с начала", "перезапусти трек пожалуйста"]
PREV = ["предыдущий трек", "предыдущая песня", "верни прошлый трек",
        "включи предыдущую", "предыдущий", "прошлый трек", "назад трек",
        "Сакура, включи предыдущую", "верни прошлый трек пожалуйста"]
OTHER = [("следующий трек", "music.next"), ("повтори трек", "music.repeat"),
         ("поставь на повтор", "music.repeat"), ("перемотай назад", None),
         ("предыдущая вкладка", "browser.tab_prev"), ("пауза", "music.play_pause")]


@pytest.mark.parametrize("phrase", RESTART)
@pytest.mark.parametrize("context", [None, "playing:music"])
def test_restart_phrases(index, phrase, context):
    m = index.match(phrase, context)
    assert m is not None and m[1].id == "music.restart", (phrase, m and m[1].id)


@pytest.mark.parametrize("phrase", PREV)
@pytest.mark.parametrize("context", [None, "playing:music"])
def test_prev_phrases(index, phrase, context):
    m = index.match(phrase, context)
    assert m is not None and m[1].id == "music.prev", (phrase, m and m[1].id)


@pytest.mark.parametrize("phrase,want", OTHER)
def test_neighbours_unchanged(index, phrase, want):
    m = index.match(phrase, None)
    assert (m[1].id if m else None) == want, phrase


def test_restart_and_prev_triggers_do_not_overlap():
    """Ни один триггер одного действия не содержится в триггере другого."""
    import re
    by_id = {d.id: d.triggers for d in load()}
    for a, b in (("music.restart", "music.prev"), ("music.prev", "music.restart")):
        for ta in by_id[a]:
            for tb in by_id[b]:
                assert not re.search(rf"(?<!\w){re.escape(ta)}(?!\w)", tb), (ta, tb)


def test_declarations():
    d = {x.id: x for x in load()}
    r, p = d["music.restart"], d["music.prev"]
    assert (r.executor, r.reversible, r.confirm, r.followup) == ("agent", True, False, "ack")
    assert "двойной шаг назад" in p.desc
    assert {"предыдущий трек", "предыдущая песня", "верни прошлый трек",
            "включи предыдущую"} <= set(p.triggers)


def test_restart_reaches_agent_and_acks():
    from modules.acks import category_for
    from sakura_core.executor import registered
    from sakura_core.bridge import _load_capabilities
    _load_capabilities()
    assert "music.restart" in registered()
    assert category_for("music.restart") == "music"


# ── golden-набор ───────────────────────────────────────────────────

# Намеренные изменения маршрутизации относительно снимка (фраза без
# контекста и без «Сакура,»/«пожалуйста» — варианты выводятся ниже).
# Все четыре — разговорные фразы, которые теперь ловят голые триггеры
# «заново» / «с начала» (заданы в спецификации). Командные триггеры не
# изменились ни в одном контексте.
INTENDED = {
    "давай начнём заново": "music.restart",
    "начни игру заново": "music.restart",
    "расскажи с начала": "music.restart",
    "объясни заново": "music.restart",
}


def _intended(key: str) -> str | None | bool:
    phrase = key.split(" | ")[0]
    for p in (phrase, phrase.removeprefix("сакура, "), phrase.removesuffix(" пожалуйста")):
        if p in INTENDED:
            return INTENDED[p]
    return False


def test_golden_no_regressions():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    current = snapshot(load(), sorted({k.split(" | ")[0] for k in golden}))
    unexpected = {}
    for key, was in golden.items():
        now = current[key]
        if now == was:
            continue
        want = _intended(key)
        if want is not False and now == want:
            continue
        unexpected[key] = (was, now)
    assert not unexpected, json.dumps(unexpected, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    decls = _decls(sys.argv[1] if len(sys.argv) > 1 else None)
    snap = snapshot(decls, golden_phrases(decls))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=0, sort_keys=True),
                      encoding="utf-8")
    print(f"{GOLDEN}: {len(snap)} записей, {sum(v is not None for v in snap.values())} с действием")
