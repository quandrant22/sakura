"""desktop.core.game_integrations — точные игровые события из официальных API игр (без разглядывания пикселей).

  • CS2 и Dota 2 — Valve Game State Integration: игра сама шлёт JSON на 127.0.0.1:GSI_PORT, если в её папке
    cfg лежит файл gamestate_integration_sakura.cfg (официальный механизм Valve, античит его не трогает).
    install_gsi(game) кладёт файл по кнопке в настройках — найдя папку игры через библиотеки Steam.
  • League of Legends — Live Client Data API (https://127.0.0.1:2999), который клиент LoL открывает сам
    во время матча; читаем только события.

Все события приводятся к общему виду: (kind, detail) — kill, multikill, death, round_win, round_loss,
bomb_planted, victory, defeat, ace, objective, low_hp. Дальше их обрабатывает game_director.
Разбор состояний — чистые функции (тесты): cs2_events / dota_events / lol_events.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

log = logging.getLogger("sakura.game_api")

GSI_PORT = 3017
GsiEvent = tuple[str, str]  # (kind, detail)

GSI_GAMES = {
    "cs2": {"title": "Counter-Strike 2", "dir": ("Counter-Strike Global Offensive", "game", "csgo", "cfg")},
    "dota2": {"title": "Dota 2", "dir": ("dota 2 beta", "game", "dota", "cfg", "gamestate_integration")},
}
CFG_NAME = "gamestate_integration_sakura.cfg"


# ── CS2 ──────────────────────────────────────────────────────────────

def cs2_events(prev: dict | None, cur: dict) -> list[GsiEvent]:
    """Разница двух состояний CS2 GSI → события. Свой игрок — player.steamid == provider.steamid."""
    out: list[GsiEvent] = []
    prev = prev or {}
    me = (cur.get("provider") or {}).get("steamid")
    p, pp = cur.get("player") or {}, prev.get("player") or {}
    if me and p.get("steamid") != me:
        return out  # наблюдаем за другим игроком (мёртв, смотрим тиммейта) — не наши события
    st, pst = p.get("state") or {}, pp.get("state") or {}
    hp, php = st.get("health"), pst.get("health")
    if isinstance(hp, int) and isinstance(php, int):
        if php > 0 and hp == 0:
            out.append(("death", ""))
        elif 0 < hp <= 20 < php:
            out.append(("low_hp", f"{hp} HP"))
    rk, prk = st.get("round_kills"), pst.get("round_kills")
    if isinstance(rk, int) and isinstance(prk, int) and rk > prk:
        if rk >= 5:
            out.append(("ace", "эйс"))
        elif rk >= 3:
            out.append(("multikill", f"{rk} за раунд"))
        else:
            out.append(("kill", ""))
    rnd, prnd = cur.get("round") or {}, prev.get("round") or {}
    if rnd.get("bomb") == "planted" and prnd.get("bomb") != "planted":
        out.append(("bomb_planted", ""))
    win, pwin = rnd.get("win_team"), prnd.get("win_team")
    team = p.get("team")
    if win and win != pwin and team:
        out.append(("round_win" if win == team else "round_loss", ""))
    mp, pmp = cur.get("map") or {}, prev.get("map") or {}
    if mp.get("phase") == "gameover" and pmp.get("phase") != "gameover" and team:
        ct, t = (mp.get("team_ct") or {}).get("score", 0), (mp.get("team_t") or {}).get("score", 0)
        mine, theirs = (ct, t) if team == "CT" else (t, ct)
        out.append(("victory" if mine > theirs else "defeat", f"{mine}:{theirs}"))
    return out


# ── Dota 2 ───────────────────────────────────────────────────────────

def dota_events(prev: dict | None, cur: dict) -> list[GsiEvent]:
    out: list[GsiEvent] = []
    prev = prev or {}
    p, pp = cur.get("player") or {}, prev.get("player") or {}
    for key, kind in (("kills", "kill"), ("deaths", "death")):
        a, b = p.get(key), pp.get(key)
        if isinstance(a, int) and isinstance(b, int) and a > b:
            out.append((kind, ""))
    ks, pks = p.get("kill_streak"), pp.get("kill_streak")
    if isinstance(ks, int) and isinstance(pks, int) and ks > pks and ks in (3, 5, 7, 10):
        out.append(("multikill", f"серия {ks}"))
    mp, pmp = cur.get("map") or {}, prev.get("map") or {}
    win, pwin = mp.get("win_team"), pmp.get("win_team")
    team = p.get("team_name")
    if win and win != "none" and win != pwin and team:
        out.append(("victory" if win == team else "defeat", ""))
    h, ph = cur.get("hero") or {}, prev.get("hero") or {}
    hp, php = h.get("health_percent"), ph.get("health_percent")
    if isinstance(hp, int) and isinstance(php, int) and 0 < hp <= 15 < php:
        out.append(("low_hp", f"{hp}%"))
    return out


# ── League of Legends ────────────────────────────────────────────────

def lol_events(events: list[dict], me: str, seen: int) -> tuple[list[GsiEvent], int]:
    """Новые события Live Client (EventID > seen) → наши события. Возвращает (события, новый seen)."""
    out: list[GsiEvent] = []
    top = seen
    for e in events:
        eid = e.get("EventID")
        if not isinstance(eid, int) or eid <= seen:
            continue
        top = max(top, eid)
        name = e.get("EventName")
        if name == "ChampionKill":
            if e.get("KillerName") == me:
                out.append(("kill", str(e.get("VictimName", ""))))
            elif e.get("VictimName") == me:
                out.append(("death", str(e.get("KillerName", ""))))
        elif name == "Multikill" and e.get("KillerName") == me:
            streak = int(e.get("KillStreak") or 2)
            name_ = {2: "дабл", 3: "трипл", 4: "квадра"}.get(streak, "пента")
            out.append(("ace" if streak >= 5 else "multikill", name_))
        elif name == "Ace" and e.get("Acer") == me:
            out.append(("ace", "эйс"))
        elif name in ("DragonKill", "BaronKill", "HeraldKill") and e.get("KillerName") == me:
            out.append(("objective", {"DragonKill": "дракон", "BaronKill": "барон", "HeraldKill": "герольд"}[name]))
        elif name == "GameEnd":
            out.append(("victory" if e.get("Result") == "Win" else "defeat", ""))
    return out, top


# ── Сервер GSI ───────────────────────────────────────────────────────

class GsiServer:
    """HTTP 127.0.0.1:GSI_PORT для CS2/Dota 2. Проверяет токен из cfg; события → on_event(game, kind, detail)."""

    def __init__(self, on_event: Callable[[str, str, str], None], port: int = GSI_PORT, token: str | None = None):
        self.on_event = on_event
        self.port = port
        self.token = token or secrets.token_hex(16)
        self._prev: dict[str, dict] = {}
        self._httpd: Optional[ThreadingHTTPServer] = None

    def handle(self, body: dict) -> list[GsiEvent]:
        if ((body.get("auth") or {}).get("token")) != self.token:
            return []
        app = ((body.get("provider") or {}).get("appid"))
        game = "cs2" if app == 730 else "dota2" if app == 570 else None
        if game is None:
            return []
        prev = self._prev.get(game)
        evs = cs2_events(prev, body) if game == "cs2" else dota_events(prev, body)
        self._prev[game] = body
        for kind, detail in evs:
            try:
                self.on_event(game, kind, detail)
            except Exception:  # noqa: BLE001
                log.exception("[gsi] обработчик события")
        return evs

    def start(self) -> bool:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    server.handle(body if isinstance(body, dict) else {})
                except Exception:  # noqa: BLE001
                    pass
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):  # тишина в журнале
                return

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as e:
            log.warning("[gsi] порт %d занят: %s", self.port, e)
            return False
        threading.Thread(target=self._httpd.serve_forever, name="gsi", daemon=True).start()
        log.info("[gsi] слушаю 127.0.0.1:%d", self.port)
        return True

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None


def gsi_cfg(token: str, port: int = GSI_PORT) -> str:
    return (
        '"Sakura"\n{\n'
        f' "uri" "http://127.0.0.1:{port}"\n'
        ' "timeout" "5.0"\n "buffer" "0.1"\n "throttle" "0.5"\n "heartbeat" "30.0"\n'
        f' "auth"\n {{\n  "token" "{token}"\n }}\n'
        ' "data"\n {\n  "provider" "1"\n  "map" "1"\n  "round" "1"\n  "player_id" "1"\n  "player_state" "1"\n'
        '  "player" "1"\n  "hero" "1"\n }\n}\n'
    )


# ── Папки Steam ──────────────────────────────────────────────────────

def parse_library_folders(vdf_text: str) -> list[str]:
    """libraryfolders.vdf → пути библиотек ("path" "D:\\\\SteamLibrary")."""
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', vdf_text or "")]


def steam_libraries() -> list[str]:
    roots: list[str] = []
    try:
        from desktop.core.platform import get_platform
        root = get_platform().steam_path()
        if root:
            roots.append(str(root).replace("/", "\\"))
    except Exception:  # noqa: BLE001
        pass
    libs: list[str] = []
    for root in roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libs.extend(parse_library_folders(f.read()))
        except OSError:
            libs.append(root)
    return list(dict.fromkeys(libs))


def gsi_dir(game: str, libraries: list[str] | None = None) -> Optional[str]:
    spec = GSI_GAMES.get(game)
    if not spec:
        return None
    for lib in libraries if libraries is not None else steam_libraries():
        base = os.path.join(lib, "steamapps", "common", spec["dir"][0])
        if os.path.isdir(base):
            return os.path.join(base, *spec["dir"][1:])
    return None


def gsi_status(game: str, libraries: list[str] | None = None) -> dict:
    d = gsi_dir(game, libraries)
    return {"game": game, "title": GSI_GAMES[game]["title"], "found": d is not None,
            "installed": bool(d and os.path.isfile(os.path.join(d, CFG_NAME)))}


def install_gsi(game: str, token: str, libraries: list[str] | None = None) -> dict:
    d = gsi_dir(game, libraries)
    if d is None:
        title = GSI_GAMES.get(game, {}).get("title", game)
        return {"ok": False, "status": "unsupported", "detail": f"{title} не найдена в библиотеках Steam"}
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, CFG_NAME), "w", encoding="utf-8") as f:
            f.write(gsi_cfg(token))
    except OSError as e:
        return {"ok": False, "status": "failed", "detail": f"не удалось записать файл: {type(e).__name__}"}
    title = GSI_GAMES[game]["title"]
    return {"ok": True, "status": "done", "detail": f"Готово — перезапусти {title}, и я буду видеть матч"}


# ── LoL: опрос Live Client ───────────────────────────────────────────

class LolPoller:
    """Пока идёт матч LoL (League of Legends.exe) — раз в 2 с читает новые события Live Client."""

    BASE = "https://127.0.0.1:2999/liveclientdata"

    def __init__(self, on_event: Callable[[str, str, str], None], interval: float = 2.0):
        self.on_event = on_event
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ctx = ssl.create_default_context()
        # Сертификат Live Client самоподписан Riot; адрес — только 127.0.0.1.
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _get(self, path: str):
        with urllib.request.urlopen(f"{self.BASE}/{path}", context=self._ctx, timeout=2) as r:  # noqa: S310
            return json.loads(r.read() or b"null")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lol-live", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        me, seen = None, -1
        while not self._stop.wait(self.interval):
            try:
                if me is None:
                    me = self._get("activeplayername")
                    if isinstance(me, str) and "#" in me:
                        me = me.split("#", 1)[0]
                    data = self._get("eventdata")
                    seen = max([e.get("EventID", -1) for e in (data or {}).get("Events", [])] + [-1])
                    continue
                data = self._get("eventdata") or {}
                evs, seen = lol_events(data.get("Events", []), str(me), seen)
                for kind, detail in evs:
                    self.on_event("lol", kind, detail)
            except Exception:  # noqa: BLE001 — матча нет / клиент закрыт
                me, seen = None, -1
                time.sleep(self.interval)
