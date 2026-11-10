"""Игры: определение по процессу, уровни присутствия, тильт, полноэкранный режим, игровые API, дирижёр."""
import json
import os

from desktop.core import fullscreen
from desktop.core import game_integrations as gi
from desktop.core import game_presence as gp
from desktop.core.game_detect import GameInfo, classify, nice_name
from desktop.core.game_director import GameDirector

# ── определение игры ──

def test_launcher_folders_and_names():
    g = classify("eldenring.exe", r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game\eldenring.exe", "ELDEN RING™")
    assert g and g.name == "ELDEN RING" and "папка игр" in g.reason
    fortnite = r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\x.exe"
    g = classify("FortniteClient-Win64-Shipping.exe", fortnite)
    assert g and g.name == "Fortnite"
    assert classify("VALORANT-Win64-Shipping.exe", r"C:\Riot Games\VALORANT\live\VALORANT.exe").name == "VALORANT"


def test_emulators_user_lists_and_never_games():
    assert classify("ryujinx.exe", r"C:\Tools\Ryujinx\Ryujinx.exe", "Ryujinx 1.2 - Zelda").reason == "эмулятор"
    assert classify("steam.exe", r"C:\Program Files (x86)\Steam\steam.exe") is None
    assert classify("chrome.exe", r"C:\x\chrome.exe", fullscreen=True, gpu=90) is None
    assert classify("mygame.exe", r"C:\Stuff\mygame.exe") is None
    assert classify("mygame.exe", r"C:\Stuff\mygame.exe", user_games=["MyGame.exe"]).reason == "в списке игр Мастера"
    elden = r"D:\steamapps\common\ELDEN RING\eldenring.exe"
    assert classify("eldenring.exe", elden, user_not_games=["eldenring.exe"]) is None


def test_fullscreen_gpu_heuristic():
    g = classify("indie.exe", r"C:\Stuff\indie.exe", "Indie", fullscreen=True, gpu=70)
    assert g.reason.startswith("во весь экран")
    assert classify("indie.exe", r"C:\Stuff\indie.exe", "Indie", fullscreen=True, gpu=10) is None
    assert classify("indie.exe", r"C:\Stuff\indie.exe", "Indie", fullscreen=False, gpu=99) is None


def test_nice_name_falls_back_to_title_then_exe():
    assert nice_name("hl2.exe", r"C:\x\hl2.exe", "Half-Life 2") == "Half-Life 2"
    assert nice_name("cool_game-Win64-Shipping.exe") == "cool game"


# ── уровни присутствия ──

def test_levels_and_gate():
    assert gp.level_for("dota2.exe", {"dota2.exe": "coop"}) == "coop"
    assert gp.level_for("x.exe", {}, "мусор") == "reactions"
    g = gp.SpeechGate()
    assert not g.should_speak("silent", "victory", 0)
    assert not g.should_speak("reactions", "death", 0)          # смерть на «Реакциях» — только всплывашка
    assert g.should_speak("reactions", "multikill", 100)
    assert not g.should_speak("reactions", "multikill", 120)    # пауза 45 с
    assert g.should_speak("reactions", "victory", 106)          # важное — через 5 с
    c = gp.SpeechGate()
    assert c.should_speak("commentator", "death", 0) and c.should_speak("commentator", "kill", 20)


def test_tilt_fires_once_per_cooldown():
    t = gp.TiltMeter()
    assert [t.death(i * 60) for i in range(4)] == [False, False, False, True]
    assert not any(t.death(300 + i) for i in range(5))  # кулдаун 15 мин
    t.win()
    assert t.deaths == []


# ── полноэкранный режим ──

def test_compat_layer_flag():
    assert fullscreen.has_flag("~ DISABLEDXMAXIMIZEDWINDOWEDMODE HIGHDPIAWARE")
    assert fullscreen.strip_flag("~ DISABLEDXMAXIMIZEDWINDOWEDMODE HIGHDPIAWARE") == "~ HIGHDPIAWARE"
    assert fullscreen.strip_flag("~ DISABLEDXMAXIMIZEDWINDOWEDMODE") == ""
    assert fullscreen.strip_flag("") == ""
    assert not fullscreen.exclusive_active() or os.name == "nt"
    assert fullscreen.advice("x.exe", False) == {"exclusive": False, "fix": None, "text": ""}


# ── игровые API ──

def _cs(hp=100, rk=0, team="CT", win=None, phase="live", bomb=None, me="1", who="1"):
    return {"provider": {"appid": 730, "steamid": me}, "player": {"steamid": who, "team": team,
            "state": {"health": hp, "round_kills": rk}}, "round": {"win_team": win, "bomb": bomb},
            "map": {"phase": phase, "team_ct": {"score": 13}, "team_t": {"score": 7}}}


def test_cs2_events():
    assert gi.cs2_events(_cs(), _cs(hp=0)) == [("death", "")]
    assert gi.cs2_events(_cs(rk=2), _cs(rk=3)) == [("multikill", "3 за раунд")]
    assert gi.cs2_events(_cs(rk=4), _cs(rk=5)) == [("ace", "эйс")]
    assert gi.cs2_events(_cs(), _cs(win="CT")) == [("round_win", "")]
    assert gi.cs2_events(_cs(), _cs(bomb="planted")) == [("bomb_planted", "")]
    assert ("victory", "13:7") in gi.cs2_events(_cs(), _cs(phase="gameover"))
    assert gi.cs2_events(_cs(), _cs(hp=0, who="2")) == []  # смотрим за тиммейтом


def test_dota_and_lol_events():
    prev = {"player": {"kills": 1, "deaths": 0, "kill_streak": 2, "team_name": "radiant"}, "map": {"win_team": "none"}}
    cur = {"player": {"kills": 2, "deaths": 0, "kill_streak": 3, "team_name": "radiant"},
           "map": {"win_team": "radiant"}}
    assert gi.dota_events(prev, cur) == [("kill", ""), ("multikill", "серия 3"), ("victory", "")]
    evs = [{"EventID": 1, "EventName": "ChampionKill", "KillerName": "Me", "VictimName": "X"},
           {"EventID": 2, "EventName": "Multikill", "KillerName": "Me", "KillStreak": 3},
           {"EventID": 3, "EventName": "ChampionKill", "KillerName": "Y", "VictimName": "Me"},
           {"EventID": 4, "EventName": "GameEnd", "Result": "Win"}]
    out, seen = gi.lol_events(evs, "Me", 0)
    assert out == [("kill", "X"), ("multikill", "трипл"), ("death", "Y"), ("victory", "")] and seen == 4
    assert gi.lol_events(evs, "Me", 4) == ([], 4)


def test_gsi_server_checks_token_and_tracks_state():
    got = []
    srv = gi.GsiServer(lambda g, k, d: got.append((g, k)), token="t")
    srv.handle({**_cs(), "auth": {"token": "bad"}})
    srv.handle({**_cs(), "auth": {"token": "t"}})
    srv.handle({**_cs(hp=0), "auth": {"token": "t"}})
    assert got == [("cs2", "death")]


def test_gsi_cfg_and_steam_libraries(tmp_path):
    vdf = ('"libraryfolders"\n{\n "0"\n {\n  "path"  "C:\\\\Program Files (x86)\\\\Steam"\n }\n'
           ' "1" { "path" "D:\\\\SteamLibrary" }\n}')
    assert gi.parse_library_folders(vdf) == [r"C:\Program Files (x86)\Steam", r"D:\SteamLibrary"]
    lib = tmp_path / "lib"
    (lib / "steamapps" / "common" / "Counter-Strike Global Offensive").mkdir(parents=True)
    st = gi.gsi_status("cs2", [str(lib)])
    assert st["found"] and not st["installed"]
    r = gi.install_gsi("cs2", "tok", [str(lib)])
    assert r["ok"]
    assert gi.gsi_status("cs2", [str(lib)])["installed"]
    cfg = (lib / "steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg" / gi.CFG_NAME).read_text("utf-8")
    assert '"token" "tok"' in cfg and f"127.0.0.1:{gi.GSI_PORT}" in cfg
    assert not gi.install_gsi("dota2", "tok", [str(lib)])["ok"]


# ── дирижёр ──

class FakeSettings(dict):
    def get(self, k, d=None):  # noqa: D401
        return super().get(k, d)

    def set(self, k, v):
        self[k] = v


class FakeClips:
    def __init__(self):
        self.saved = 0

    def save_clip(self, seconds):
        self.saved += 1
        from pathlib import Path
        return Path("clip.mp4")

    def add_frame(self, b):
        pass


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


ELDEN = GameInfo("elden.exe", "ELDEN RING", "elden.exe", "C:/e.exe", "папка игр")


def _director(level="reactions", game=ELDEN):
    emitted, sent = [], []
    clock = Clock()
    s = FakeSettings(game_presence={"elden.exe": level}, game_autoclip=False)
    state = {"game": game}
    d = GameDirector(s, emit=emitted.append, send_server=sent.append, clips=FakeClips(),
                     detect=lambda: (state["game"], None), clock=clock)
    d._start_sense = lambda s: None  # без захвата экрана в тестах
    return d, emitted, sent, clock, state


def test_session_lifecycle_and_grace():
    d, emitted, sent, clock, state = _director()
    d.tick()
    assert d.session and d.session.level == "reactions"
    assert sent[0]["type"] == "game_session_start"
    state["game"] = None
    clock.t += 60
    d.tick()
    assert d.session is not None  # Alt+Tab — сессия жива
    clock.t += 400
    d.tick()
    assert d.session is None
    assert any(e.get("type") == "game_session" and e.get("state") == "end" for e in emitted)
    assert sent[-1]["type"] == "game_session_end"


def test_events_go_to_stage_and_voice_by_level():
    d, emitted, sent, clock, _ = _director("reactions")
    d.tick()
    d.on_event("death")
    assert emitted[-1]["event"] == "death"
    assert not [m for m in sent if m["type"] == "game_event"]   # смерть на «Реакциях» не озвучивается
    d.on_event("multikill", "3 за раунд")
    assert [m["event"] for m in sent if m["type"] == "game_event"] == ["multikill"]
    clock.t += 10
    for _ in range(3):
        d.on_event("death")
    assert any(m.get("event") == "tilt" for m in sent)            # 4 смерти → поддержка
    assert d.session.stats["deaths"] == 4


def test_silent_level_never_speaks_but_counts():
    d, emitted, sent, clock, _ = _director("silent")
    d.tick()
    d.on_event("victory")
    assert d.session.stats["wins"] == 1
    assert not [m for m in sent if m["type"] == "game_event"]
    assert emitted[-1]["event"] == "victory"


def test_set_level_persists_and_applies_to_session():
    d, *_ = _director("reactions")
    d.tick()
    assert d.set_level("elden.exe", "coop") == "coop"
    assert d.session.level == "coop"
    assert d.settings["game_presence"]["elden.exe"] == "coop"
    assert json.dumps(d.snapshot())
