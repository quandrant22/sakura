"""Видео-источники: разбор ссылок (youtube_embed / url_hls), вкладка браузера
(remote_browser через расширение), самопроверка связи с YouTube."""
import re
import urllib.request
from urllib.parse import parse_qs, urlparse

YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
            "www.youtube-nocookie.com")
YT_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
STREAM_EXT = {".m3u8": "hls", ".mp4": "file", ".webm": "file", ".ogv": "file", ".mov": "file", ".m4v": "file"}


def _seconds(t: str) -> int:
    """t=90 | t=1m30s | t=1h2m3s → секунды."""
    if not t:
        return 0
    if t.isdigit():
        return int(t)
    total = 0
    for num, unit in re.findall(r"(\d+)([hms])", t):
        total += int(num) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def classify_url(url: str) -> dict:
    """Что за ссылка: youtube (video_id, start) | hls | file. ValueError — не поддерживается."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https"):
        raise ValueError("нужна ссылка http(s)")
    host = (u.hostname or "").lower()
    if host in YT_HOSTS:
        qs = parse_qs(u.query)
        if host == "youtu.be":
            vid = u.path.strip("/").split("/")[0]
        elif u.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = u.path.split("/")[2]
        else:
            vid = (qs.get("v") or [""])[0]
        if not YT_ID.fullmatch(vid or ""):
            raise ValueError("не нашла id видео YouTube")
        return {"kind": "youtube", "video_id": vid, "start": _seconds((qs.get("t") or qs.get("start") or [""])[0])}
    path = u.path.lower()
    for ext, kind in STREAM_EXT.items():
        if path.endswith(ext):
            return {"kind": kind, "url": url.strip()}
    raise ValueError("поддерживаются YouTube, .mp4, .webm и .m3u8")


def browser_url(video_id: str, time_s: float = 0) -> str:
    """«Верни в браузер»: ссылка на то же место видео."""
    return f"https://www.youtube.com/watch?v={video_id}&t={max(0, int(time_s))}s"


async def take_from_browser(send_command) -> dict:
    """Подхват видео из вкладки: video_id и currentTime от расширения, вкладка — на паузу.

    send_command — extension_server.send_command (async). Ответ page_content_youtube:
    {ok, result: {title, channel, video_id, currentTime, paused, url}}.
    """
    r = await send_command("page_content_youtube", "")
    if not r or not r.get("ok"):
        raise ValueError((r or {}).get("error") or "нет открытого видео YouTube")
    res = r.get("result") or {}
    vid = res.get("video_id") or ""
    if not YT_ID.fullmatch(vid):
        raise ValueError("расширение не вернуло id видео")
    if not res.get("paused"):
        await send_command("youtube_pause", "")
    return {"video_id": vid, "start": int(res.get("currentTime") or 0), "title": res.get("title", ""),
            "channel": res.get("channel", "")}


def check_youtube(proxy: str = "", timeout: float = 5.0, opener=None) -> dict:
    """Самопроверка связи с youtube.com и i.ytimg.com (через YOUTUBE_PROXY, если задан)."""
    if opener is None:
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else \
            [urllib.request.ProxyHandler({})]
        opener = urllib.request.build_opener(*handlers)
    out = {}
    for name, url in (("youtube.com", "https://www.youtube.com/generate_204"),
                      ("i.ytimg.com", "https://i.ytimg.com/generate_204")):
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Sakura/1.0"})
            with opener.open(req, timeout=timeout) as r:
                out[name] = {"ok": 200 <= r.status < 400, "status": r.status}
        except Exception as e:
            out[name] = {"ok": False, "error": type(e).__name__}
    return out
