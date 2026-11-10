"""Сервер: память игровых сессий, промпты реакций, частота реплик, тишина только при «Молчит»."""
from modules import game_sessions as gs


def test_record_and_last(tmp_path):
    p = str(tmp_path / "g.json")
    assert gs.last_session("elden.exe", p) is None
    for i in range(12):
        gs.record_session("elden.exe", "ELDEN RING", 30 + i, {"deaths": i, "x": "мусор"}, ["босс"],
                          now=1000 + i, path=p)
    last = gs.last_session("elden.exe", p)
    assert last["minutes"] == 41 and last["stats"] == {"deaths": 11}
    assert len(gs._load(p)["elden.exe"]) == gs.KEEP_PER_GAME


def test_prompts():
    pr = gs.event_prompt("Dota 2", "coop", "серия смертей подряд", "", 40, {"kills": 2, "deaths": 9})
    assert "Dota 2" in pr and "тильт" in pr and "смертей 9" in pr
    last = {"ts": 0, "minutes": 50, "stats": {"wins": 1}, "highlights": ["эйс"]}
    assert "эйс" in gs.start_prompt("CS2", last, now=4 * 3600)
    assert gs.start_prompt("CS2", last, now=3600) is None          # недавно играл — не напоминаем
    assert gs.start_prompt("CS2", {"ts": 0, "stats": {}, "highlights": []}, now=10**6) is None
    assert "итог" in gs.end_prompt("CS2", 60, {"kills": 30}, [])


def test_rate_limit_and_presence():
    gs._last_spoken.clear()
    assert gs.may_speak("pc", "reactions", "kill", now=100)
    assert not gs.may_speak("pc", "reactions", "kill", now=110)
    assert gs.may_speak("pc", "reactions", "victory", now=106)
    assert not gs.may_speak("pc", "silent", "victory", now=10**6)
    gs.set_level("pc", "coop")
    assert gs.presence_level("pc") == "coop"
    gs.clear_level("pc")
    assert gs.presence_level("pc") is None
