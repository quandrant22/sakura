"""
modules/youtube.py (VPS) — YouTube Data API v3.

Поиск видео, каналов, плейлистов. Информация о видео.
Управление плеером — через хоткеи на агенте (browser.py).

Команды (action в WS):
  youtube_search:<query>       — поиск видео
  youtube_channel:<query>      — поиск канала
  youtube_playlist:<query>     — поиск плейлиста
  youtube_info:<video_id>      — инфо о видео
  youtube_play:<video_id>      — открыть видео в браузере
  youtube_trending             — популярные видео (RU)

Хоткеи плеера (через агент browser.py):
  youtube_pause                — пауза / воспроизведение
  youtube_fullscreen           — полный экран
  youtube_forward              — +10 секунд
  youtube_rewind               — -10 секунд
  youtube_forward5             — +5 секунд
  youtube_rewind5              — -5 секунд
  youtube_next                 — следующее видео
  youtube_mute                 — звук вкл/выкл
  youtube_sub_toggle           — субтитры вкл/выкл
  youtube_volume_up            — громче
  youtube_volume_down          — тише
  youtube_speed_up             — быстрее (>)
  youtube_speed_down           — медленнее (<)
  youtube_like                 — лайк
  youtube_dislike              — дизлайк (убрать лайк)
  youtube_mini                 — мини-плеер
  youtube_theater              — театральный режим
"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("sakura.youtube")

YT_API_KEY  = "AIzaSyCyaxX1fnm6Tzsz8An1TtLVac5-KUWCdjA"
YT_BASE     = "https://www.googleapis.com/youtube/v3"
YT_WATCH    = "https://www.youtube.com/watch?v="
YT_PLAYLIST = "https://www.youtube.com/playlist?list="


# ── Data API ─────────────────────────────────────────────────────────

def _fetch(url: str) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.error(f"[youtube] API: {e}")
        return None


def _search(query: str, search_type: str = "video", max_results: int = 5) -> list[dict]:
    """Поиск видео/каналов/плейлистов."""
    params = urllib.parse.urlencode({
        "part":       "snippet",
        "q":          query,
        "type":       search_type,
        "maxResults": max_results,
        "regionCode": "RU",
        "relevanceLanguage": "ru",
        "key":        YT_API_KEY,
    })
    data = _fetch(f"{YT_BASE}/search?{params}")
    if not data:
        return []
    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        id_obj  = item.get("id", {})
        results.append({
            "title":       snippet.get("title", ""),
            "channel":     snippet.get("channelTitle", ""),
            "description": snippet.get("description", "")[:100],
            "video_id":    id_obj.get("videoId"),
            "channel_id":  id_obj.get("channelId"),
            "playlist_id": id_obj.get("playlistId"),
            "thumbnail":   snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        })
    return results


def _video_info(video_id: str) -> Optional[dict]:
    """Детальная информация о видео."""
    params = urllib.parse.urlencode({
        "part": "snippet,contentDetails,statistics",
        "id":   video_id,
        "key":  YT_API_KEY,
    })
    data = _fetch(f"{YT_BASE}/videos?{params}")
    if not data or not data.get("items"):
        return None
    item     = data["items"][0]
    snippet  = item.get("snippet", {})
    stats    = item.get("statistics", {})
    details  = item.get("contentDetails", {})
    duration = _parse_duration(details.get("duration", ""))
    return {
        "title":       snippet.get("title", ""),
        "channel":     snippet.get("channelTitle", ""),
        "description": snippet.get("description", "")[:200],
        "views":       int(stats.get("viewCount", 0)),
        "likes":       int(stats.get("likeCount", 0)),
        "duration":    duration,
        "video_id":    video_id,
        "url":         f"{YT_WATCH}{video_id}",
        "published":   snippet.get("publishedAt", "")[:10],
    }


def _trending(region: str = "RU", max_results: int = 5) -> list[dict]:
    """Популярные видео."""
    params = urllib.parse.urlencode({
        "part":        "snippet,statistics",
        "chart":       "mostPopular",
        "regionCode":  region,
        "maxResults":  max_results,
        "key":         YT_API_KEY,
    })
    data = _fetch(f"{YT_BASE}/videos?{params}")
    if not data:
        return []
    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        stats   = item.get("statistics", {})
        results.append({
            "title":   snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "views":   int(stats.get("viewCount", 0)),
            "video_id": item["id"],
        })
    return results


def _playlist_items(playlist_id: str, max_results: int = 10) -> list[dict]:
    """Видео из плейлиста."""
    params = urllib.parse.urlencode({
        "part":       "snippet",
        "playlistId": playlist_id,
        "maxResults": max_results,
        "key":        YT_API_KEY,
    })
    data = _fetch(f"{YT_BASE}/playlistItems?{params}")
    if not data:
        return []
    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        results.append({
            "title":    snippet.get("title", ""),
            "channel":  snippet.get("videoOwnerChannelTitle", ""),
            "video_id": snippet.get("resourceId", {}).get("videoId"),
        })
    return results


def _parse_duration(iso: str) -> str:
    """PT1H2M3S → 1:02:03"""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return "?"
    h, mn, s = (int(x or 0) for x in m.groups())
    if h:
        return f"{h}:{mn:02d}:{s:02d}"
    return f"{mn}:{s:02d}"


def _fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


# ── Точка входа ───────────────────────────────────────────────────────

async def youtube_command(action: str) -> dict:
    """Вызывается из main.py, action — строка команды."""

    if action.startswith("youtube_search:"):
        q       = action[len("youtube_search:"):]
        results = await asyncio.to_thread(_search, q, "video", 5)
        if not results:
            return {"ok": False, "result": "Ничего не нашла на YouTube"}
        items = []
        for r in results:
            line = f"{r['channel']} — {r['title']}"
            if r["video_id"]:
                line += f" [watch?v={r['video_id']}]"
            items.append(line)
        return {
            "ok": True, "result": results[0]["title"],
            "items": items, "first_id": results[0].get("video_id"),
            "first_url": f"{YT_WATCH}{results[0]['video_id']}" if results[0].get("video_id") else "",
            "open_youtube_url": f"{YT_WATCH}{results[0]['video_id']}" if results[0].get("video_id") else "",
        }

    if action.startswith("youtube_channel:"):
        q       = action[len("youtube_channel:"):]
        results = await asyncio.to_thread(_search, q, "channel", 3)
        if not results:
            return {"ok": False, "result": "Канал не найден"}
        items = [r["title"] for r in results]
        return {"ok": True, "result": results[0]["title"], "items": items,
                "first_channel_id": results[0].get("channel_id")}

    if action.startswith("youtube_playlist:"):
        q       = action[len("youtube_playlist:"):]
        results = await asyncio.to_thread(_search, q, "playlist", 3)
        if not results:
            return {"ok": False, "result": "Плейлист не найден"}
        # Берём видео из первого плейлиста
        pid    = results[0].get("playlist_id")
        videos = await asyncio.to_thread(_playlist_items, pid, 5) if pid else []
        items  = [f"{r['title']} ({r['channel']})" for r in videos]
        return {
            "ok": True, "result": results[0]["title"],
            "playlist_id": pid,
            "playlist_url": f"{YT_PLAYLIST}{pid}" if pid else "",
            "items": items,
        }

    if action.startswith("youtube_info:"):
        vid  = action[len("youtube_info:"):]
        info = await asyncio.to_thread(_video_info, vid)
        if not info:
            return {"ok": False, "result": "Видео не найдено"}
        result = (
            f"{info['channel']} — {info['title']} "
            f"({info['duration']}, {_fmt_views(info['views'])} просмотров)"
        )
        return {"ok": True, "result": result, "info": info}

    if action.startswith("youtube_play:"):
        vid = action[len("youtube_play:"):]
        url = f"{YT_WATCH}{vid}"
        return {"ok": True, "result": url, "open_youtube_url": url}

    if action == "youtube_trending":
        results = await asyncio.to_thread(_trending, "RU", 5)
        if not results:
            return {"ok": False, "result": "Не удалось получить тренды"}
        items = [f"{r['channel']} — {r['title']} ({_fmt_views(r['views'])} просмотров)"
                 for r in results]
        return {"ok": True, "result": "Тренды YouTube", "items": items}

    # Команды плеера — выполняются на агенте (browser.py)
    # Они приходят сюда только для логирования/ответа, само действие делает агент
    player_labels = {
        "youtube_pause":       "пауза/воспроизведение",
        "youtube_fullscreen":  "полный экран",
        "youtube_forward":     "вперёд +10с",
        "youtube_rewind":      "назад -10с",
        "youtube_forward5":    "вперёд +5с",
        "youtube_rewind5":     "назад -5с",
        "youtube_next":        "следующее видео",
        "youtube_mute":        "звук вкл/выкл",
        "youtube_sub_toggle":  "субтитры",
        "youtube_volume_up":   "громче",
        "youtube_volume_down": "тише",
        "youtube_speed_up":    "быстрее",
        "youtube_speed_down":  "медленнее",
        "youtube_like":        "лайк",
        "youtube_mini":        "мини-плеер",
        "youtube_theater":     "театральный режим",
    }
    if action in player_labels:
        return {"ok": True, "result": player_labels[action], "player_cmd": action}

    return {"ok": False, "result": f"Неизвестная YouTube команда: {action}"}