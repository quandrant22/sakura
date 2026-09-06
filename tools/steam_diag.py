#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import config
except Exception as e:
    print(f"ERROR: cannot import config: {e}")
    sys.exit(1)


def redacted_key(key: str) -> str:
    if not key:
        return "NOT SET"
    return f"set, len={len(key)}, prefix={key[:4]}..."


def validate_steam_id(sid: str) -> str:
    if not sid:
        return "NOT SET"
    if sid.isdigit() and len(sid) == 17 and sid.startswith("7656119"):
        return "valid"
    if sid.isdigit():
        return f"invalid format (digits only, len={len(sid)})"
    return f"invalid format ({len(sid)} chars, not SteamID64)"


def fetch(url: str):
    info = {"status": None, "body": None, "data": None, "error": None}
    req = urllib.request.Request(url, headers={"User-Agent": "sakura-steam-diag/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            info["status"] = r.status
            body = r.read().decode("utf-8", "replace")
            info["body"] = body
            try:
                info["data"] = json.loads(body)
            except json.JSONDecodeError:
                info["error"] = "invalid_json"
    except urllib.error.HTTPError as e:
        info["status"] = e.code
        body = e.read().decode("utf-8", "replace")
        info["body"] = body
        try:
            info["data"] = json.loads(body)
        except json.JSONDecodeError:
            info["error"] = "invalid_json"
        info["error"] = f"HTTPError {e.code}"
    except Exception as e:
        info["error"] = str(e)
    return info


def dump_response(label: str, info: dict):
    print(f"\n=== {label} ===")
    print(f"status: {info.get('status')}")
    if info.get("error"):
        print(f"error: {info['error']}")
    body = info.get("body")
    if body is not None:
        snippet = body[:300].replace("\n", " ")
        print(f"body: {snippet}{'...' if len(body) > 300 else ''}")
    data = info.get("data")
    if data is not None:
        if isinstance(data, dict) and not data:
            print("parsed: {} (empty JSON object)")
        else:
            print(f"parsed: {type(data).__name__}")


def check_privacy(data):
    if isinstance(data, dict):
        if data.get("response") == {}:
            return "response_empty"
        ps = data.get("playerstats")
        if isinstance(ps, dict) and ps.get("error"):
            return "playerstats_private"
    return None


def main():
    key = config.STEAM_KEY.strip()
    sid = config.STEAM_ID.strip()
    print("STEAM diagnostics")
    print("=================")
    print(f"STEAM_KEY: {redacted_key(key)}")
    print(f"STEAM_ID: {sid or 'NOT SET'}")
    print(f"STEAM_ID status: {validate_steam_id(sid)}")

    if not key or not sid:
        print("\nWARNING: STEAM_KEY and STEAM_ID must be set in .env or environment.")

    summary_url = (
        "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        f"?key={urllib.parse.quote(key)}&steamids={urllib.parse.quote(sid)}&format=json"
    )
    owned_url = (
        "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={urllib.parse.quote(key)}&steamid={urllib.parse.quote(sid)}"
        "&include_appinfo=1&include_played_free_games=1&format=json"
    )
    recent_url = (
        "http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
        f"?key={urllib.parse.quote(key)}&steamid={urllib.parse.quote(sid)}&count=10&format=json"
    )

    results = {}
    results["summaries"] = fetch(summary_url)
    results["owned"] = fetch(owned_url)
    results["recent"] = fetch(recent_url)

    dump_response("GetPlayerSummaries", results["summaries"])
    if check_privacy(results["summaries"].get("data")) == "response_empty":
        print("HINT: profile or game data may be private (empty response). \nPlease check Steam Privacy > Game details and profile visibility.")
    dump_response("GetOwnedGames", results["owned"])
    hint = check_privacy(results["owned"].get("data"))
    if hint == "response_empty":
        print("HINT: owned games response empty. Game details are likely not public.")
    dump_response("GetRecentlyPlayedGames", results["recent"])

    first_app_id = None
    first_app_name = None
    candidate_games = []
    if results["recent"].get("data"):
        recent_games = results["recent"]["data"].get("response", {}).get("games", [])
        candidate_games.extend((g.get("appid"), g.get("name")) for g in recent_games if g.get("appid"))
    if results["owned"].get("data"):
        owned_games = results["owned"]["data"].get("response", {}).get("games", [])
        if not candidate_games:
            owned_games = sorted(owned_games, key=lambda g: g.get("playtime_forever", 0), reverse=True)
            candidate_games.extend((g.get("appid"), g.get("name")) for g in owned_games[:10] if g.get("appid"))

    db_path = getattr(config, "MEMORY_DB_PATH", "memory/sakura.db")
    print(f"\nLocal DB path: {db_path}")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='steam_games'")
            has_table = cur.fetchone()[0] == 1
            if has_table:
                cur.execute("SELECT count(*) FROM steam_games")
                total = cur.fetchone()[0]
                print(f"steam_games rows: {total}")
                cur.execute(
                    "SELECT appid, name, playtime_forever FROM steam_games ORDER BY playtime_forever DESC LIMIT 5"
                )
                rows = cur.fetchall()
                print("Top 5 steam_games by playtime_forever:")
                for appid, name, pt in rows:
                    print(f"  {appid}\t{pt} min\t{name}")
                    if first_app_id is None:
                        first_app_id = appid
                        first_app_name = name
            else:
                print("steam_games table not found in DB.")
            conn.close()
        except Exception as e:
            print(f"ERROR reading DB: {e}")
    else:
        print("Local DB file not found.")

    if candidate_games:
        achievement_info = None
        achievement_hint = None
        for appid, name in candidate_games:
            achieve_url = (
                "http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
                f"?appid={appid}&key={urllib.parse.quote(key)}&steamid={urllib.parse.quote(sid)}&format=json&l=russian"
            )
            info = fetch(achieve_url)
            reason = None
            if info.get("status") == 200 and isinstance(info.get("data"), dict):
                ps = info["data"].get("playerstats", {})
                error = ps.get("error")
                if error == "Requested app has no stats":
                    print(f"Game {name} ({appid}) has no stats, trying next candidate...")
                    continue
                if error == "Profile is not public":
                    reason = "playerstats_private"
                achievement_info = (appid, name, info)
                achievement_hint = reason
                break
            if info.get("status") in (401, 403):
                reason = "invalid_key"
                achievement_info = (appid, name, info)
                achievement_hint = reason
                break
        if achievement_info:
            first_app_id, first_app_name, results["achievements"] = achievement_info
            print(f"\nUsing appid {first_app_id} ({first_app_name}) for GetPlayerAchievements")
            dump_response("GetPlayerAchievements", results["achievements"])
            if achievement_hint == "playerstats_private":
                print("HINT: playerstats are private. Steam Game details are not public.")
            elif results["achievements"].get("status") in (401, 403):
                print("HINT: invalid Steam key or access denied for achievements.")
        else:
            print("No game with Steam achievements data found among recent/owned candidates.")
    else:
        print("No candidate game available for GetPlayerAchievements test.")

    print("\nNOTE: Profile public and Game details public are separate Steam privacy settings.")
    print("If Game details are not public, owned games and achievements may be inaccessible even if the profile is visible.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
