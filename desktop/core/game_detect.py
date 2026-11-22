"""desktop.core.game_detect — играет ли Мастер сейчас и во что: по процессу активного окна, не по заголовку.

Раньше игра узнавалась по ключевым словам в заголовке и по Steam: Epic, GOG, Riot, Battle.net, VK Play,
эмуляторы и всё без «игрового» заголовка проходили мимо. Теперь решает путь к exe:
  1. список Мастера: «это игра» (game_processes) и «это не игра» (game_not_processes) — главнее всего;
  2. exe лежит в папке игр лаунчера (steamapps\\common, Epic Games, GOG, Riot Games, …) или это эмулятор;
  3. окно на весь монитор без рамки + видеокарта нагружена (≥ GPU_BUSY) — похоже на игру.
Лаунчеры, оверлеи и браузеры игрой не считаются никогда.

classify() — чистая функция (тесты); foreground_game() — то же для текущего окна Windows.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable, Optional

log = logging.getLogger("sakura.game_detect")

# Части пути (в нижнем регистре, с разделителями \\) — папки игр лаунчеров.
LAUNCHER_DIRS = (
    "\\steamapps\\common\\", "\\epic games\\", "\\gog galaxy\\games\\", "\\gog games\\", "\\riot games\\",
    "\\ea games\\", "\\origin games\\", "\\ubisoft game launcher\\games\\", "\\xboxgames\\",
    "\\amazon games\\library\\", "\\rockstar games\\", "\\itch\\apps\\", "\\vk play\\", "\\gamecenter\\",
    "\\lesta\\", "\\wargaming.net\\", "\\battle.net\\games\\", "\\blizzard entertainment\\",
    "\\overwatch\\", "\\world of warcraft\\", "\\diablo iv\\", "\\hearthstone\\", "\\minecraft launcher\\",
    "\\games\\",
)
KNOWN_GAMES: dict[str, str] = {
    "cs2.exe": "Counter-Strike 2",
    "csgo.exe": "Counter-Strike: Global Offensive",
    "dota2.exe": "Dota 2",
    "league of legends.exe": "League of Legends",
    "valorant.exe": "VALORANT",
    "valorant-win64-shipping.exe": "VALORANT",
    "overwatch.exe": "Overwatch 2",
    "gta5.exe": "Grand Theft Auto V",
    "gtav.exe": "Grand Theft Auto V",
    "rdr2.exe": "Red Dead Redemption 2",
    "cyberpunk2077.exe": "Cyberpunk 2077",
    "witcher3.exe": "The Witcher 3: Wild Hunt",
    "genshinimpact.exe": "Genshin Impact",
    "starrail.exe": "Honkai: Star Rail",
    "zenlesszonezero.exe": "Zenless Zone Zero",
    "minecraft.exe": "Minecraft",
    "apex.exe": "Apex Legends",
    "r5apex.exe": "Apex Legends",
    "deadlock.exe": "Deadlock",
    "rust.exe": "Rust",
    "rustclient.exe": "Rust",
    "escapefromtarkov.exe": "Escape from Tarkov",
    "warframe.x64.exe": "Warframe",
    "helldivers2.exe": "HELLDIVERS 2",
    "baldursgate3.exe": "Baldur's Gate 3",
    "bg3.exe": "Baldur's Gate 3",
    "bg3_dx11.exe": "Baldur's Gate 3",
    "eldenring.exe": "ELDEN RING",
    "starfield.exe": "Starfield",
    "terraria.exe": "Terraria",
    "stardew valley.exe": "Stardew Valley",
    "osu!.exe": "osu!",
    "worldoftanks.exe": "Мир танков",
    "palworld-win64-shipping.exe": "Palworld",
    "palworld.exe": "Palworld",
    "satisfactory-win64-shipping.exe": "Satisfactory",
    "factorygame-win64-shipping.exe": "Satisfactory",
    "rainbowsix.exe": "Rainbow Six Siege",
    "rocketleague.exe": "Rocket League",
    "tslgame.exe": "PUBG: BATTLEGROUNDS",
    "subnautica.exe": "Subnautica",
    "hollow_knight.exe": "Hollow Knight",
    "hades.exe": "Hades",
    "hades2.exe": "Hades II",
    "stalker2-win64-shipping.exe": "S.T.A.L.K.E.R. 2",
    "stalker2.exe": "S.T.A.L.K.E.R. 2",
    "b1-win64-shipping.exe": "Black Myth: Wukong",
    "darksoulsiii.exe": "Dark Souls III",
    "darksoulsremastered.exe": "Dark Souls Remastered",
    "monsterhunterworld.exe": "Monster Hunter: World",
    "monsterhunterwilds.exe": "Monster Hunter Wilds",
    "destiny2.exe": "Destiny 2",
    "fallguys_client.exe": "Fall Guys",
    "scrapmechanic.exe": "Scrap Mechanic",
    "scrap mechanic.exe": "Scrap Mechanic",
    "scrapmechanic_x64.exe": "Scrap Mechanic",
}
EMULATORS = frozenset({
    "yuzu.exe", "suyu.exe", "citron.exe", "ryujinx.exe", "rpcs3.exe", "pcsx2.exe", "pcsx2-qt.exe", "dolphin.exe",
    "retroarch.exe", "cemu.exe", "ppsspp.exe", "ppssppwindows64.exe", "xenia.exe", "xenia_canary.exe",
    "vita3k.exe", "shadps4.exe", "melonds.exe", "mgba.exe", "citra-qt.exe", "lime3ds.exe", "azahar.exe",
    "duckstation-qt-x64-releaseltcg.exe", "eden.exe",
})
# Не игры, даже если лежат в папке лаунчера или во весь экран.
NOT_GAMES = frozenset({
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "epicwebhelper.exe", "galaxyclient.exe",
    "riotclientservices.exe", "riotclientux.exe", "leagueclient.exe", "leagueclientux.exe", "battle.net.exe",
    "eadesktop.exe", "origin.exe", "upc.exe", "ubisoftconnect.exe", "rockstarlauncher.exe", "gamecenter.exe",
    "vkplay.exe", "lgc.exe", "wgc.exe", "minecraftlauncher.exe", "unitycrashhandler64.exe", "crashreporter.exe",
    "easyanticheat.exe", "easyanticheat_eos_setup.exe", "beservice.exe", "explorer.exe", "chrome.exe",
    "msedge.exe", "firefox.exe", "opera.exe", "browser.exe", "yandex.exe", "discord.exe", "telegram.exe",
    "obs64.exe", "vlc.exe", "mpv.exe", "potplayermini64.exe", "electron.exe", "sakura.exe", "code.exe",
    "applicationframehost.exe", "searchhost.exe", "shellexperiencehost.exe", "lockapp.exe",
})
# Видеокарта занята — для запасного правила «во весь экран + нагрузка».
GPU_BUSY = 40.0


@dataclass(frozen=True)
class GameInfo:
    key: str          # нормализованное имя exe (ключ настроек «уровень присутствия»)
    name: str         # как называть игру вслух
    exe: str          # имя exe
    path: str = ""    # полный путь exe
    reason: str = ""  # почему решили, что это игра (для журнала и настроек)


def _norm(p: str) -> str:
    return (p or "").replace("/", "\\").lower()


def game_key(exe: str) -> str:
    return (exe or "").strip().lower()


def nice_name(exe: str, path: str = "", title: str = "") -> str:
    """Название игры: папка в steamapps\\common / Epic Games / … → иначе заголовок окна → иначе имя exe."""
    low = _norm(path)
    for d in LAUNCHER_DIRS:
        i = low.find(d)
        if i >= 0 and d != "\\games\\":
            rest = path[i + len(d):].replace("/", "\\")
            folder = rest.split("\\", 1)[0].strip()
            if folder:
                return folder
    t = (title or "").strip()
    if t and len(t) <= 60:
        return t
    key = game_key(exe)
    if key in KNOWN_GAMES:
        return KNOWN_GAMES[key]
    stem = os.path.splitext(exe or "")[0]
    while True:  # Game-Win64-Shipping → Game
        cut = re.sub(r"[-_](win64|win32|x64|shipping|dx11|dx12|vulkan|client)$", "", stem, flags=re.I)
        if cut == stem:
            break
        stem = cut
    return re.sub(r"[_\-]+", " ", stem).strip() or exe


def classify(exe: str, path: str = "", title: str = "", *, fullscreen: bool = False, gpu: float | None = None,
             user_games: Iterable[str] = (), user_not_games: Iterable[str] = ()) -> Optional[GameInfo]:
    key = game_key(exe)
    if not key:
        return None
    games = {game_key(x) for x in user_games if str(x).strip()}
    not_games = {game_key(x) for x in user_not_games if str(x).strip()}
    if key in not_games:
        return None
    if key in games:
        return GameInfo(key, nice_name(exe, path, title), exe, path, "в списке игр Мастера")
    if key in NOT_GAMES:
        return None
    if key in EMULATORS:
        return GameInfo(key, nice_name(exe, "", title), exe, path, "эмулятор")
    low = _norm(path)
    for d in LAUNCHER_DIRS:
        if d in low:
            return GameInfo(key, nice_name(exe, path, title), exe, path, f"папка игр ({d.strip(chr(92))})")
    if key in KNOWN_GAMES:
        return GameInfo(key, KNOWN_GAMES[key], exe, path, "известная игра")
    if fullscreen and gpu is not None and gpu >= GPU_BUSY:
        return GameInfo(key, nice_name(exe, path, title), exe, path, "во весь экран и нагружает видеокарту")
    return None


# ── Windows: активное окно ──────────────────────────────────────────

def _foreground() -> dict | None:
    """{hwnd, title, exe, path, fullscreen, monitor} активного окна или None (не Windows)."""
    try:
        import psutil
        import win32api
        import win32con
        import win32gui
        import win32process
    except Exception:  # noqa: BLE001
        return None
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        exe, path = proc.name(), proc.exe()
    except Exception:  # noqa: BLE001
        return None
    fullscreen = False
    monitor = None
    try:
        rect = win32gui.GetWindowRect(hwnd)
        hmon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitor = tuple(win32api.GetMonitorInfo(hmon)["Monitor"])
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        covers = rect[0] <= monitor[0] and rect[1] <= monitor[1] and rect[2] >= monitor[2] and rect[3] >= monitor[3]
        fullscreen = covers and not (style & win32con.WS_CAPTION == win32con.WS_CAPTION)
    except Exception:  # noqa: BLE001
        pass
    return {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "exe": exe, "path": path,
            "fullscreen": fullscreen, "monitor": monitor}


def foreground_game(user_games: Iterable[str] = (), user_not_games: Iterable[str] = (),
                    gpu: float | None = None) -> tuple[Optional[GameInfo], dict | None]:
    fg = _foreground()
    if not fg:
        return None, None
    info = classify(fg["exe"], fg["path"], fg["title"], fullscreen=fg["fullscreen"], gpu=gpu,
                    user_games=user_games, user_not_games=user_not_games)
    return info, fg
