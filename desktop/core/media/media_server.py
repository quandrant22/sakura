"""desktop.core.media.media_server — локальный http для встроенных плееров.

Только 127.0.0.1, токен в каждом запросе (?t=…), проверка заголовка Host
(защита от DNS rebinding). Маршруты:
  GET/HEAD /media/<id>              файл трека/видео (Range, 206/416)
  GET      /cover/<sha1>            обложка из кэша медиатеки
  GET      /subtitle/<id>/<n>       субтитры (.vtt как есть, .srt → WebVTT)
  GET      /youtube/player.html     страница плеера YouTube IFrame API
Файлы отдаются ТОЛЬКО через медиатеку и только из папок владельца
(MediaLibrary.is_allowed: realpath + commonpath).

YouTube: страница грузится с http://127.0.0.1:<порт> (не file:// — иначе ошибка
153), iframe с referrerpolicy="strict-origin-when-cross-origin", enablejsapi=1 и
origin этого сервера. Реклама и сам плеер не трогаются: страница только
передаёт команды play/pause/seek через официальный API и сообщает состояние.
"""
import html
import logging
import mimetypes
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("sakura.media")

MIME = {".flac": "audio/flac", ".opus": "audio/ogg", ".ogg": "audio/ogg", ".oga": "audio/ogg",
        ".m4a": "audio/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm", ".mp4": "video/mp4",
        ".m4v": "video/mp4", ".mov": "video/quicktime", ".ogv": "video/ogg", ".mp3": "audio/mpeg",
        ".wav": "audio/wav", ".aac": "audio/aac", ".wma": "audio/x-ms-wma", ".avi": "video/x-msvideo"}
CHUNK = 256 * 1024
YT_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def srt_to_vtt(text: str) -> str:
    body = re.sub(r"(\d\d:\d\d:\d\d),(\d\d\d)", r"\1.\2", text.replace("\r\n", "\n").lstrip("\ufeff"))
    return "WEBVTT\n\n" + body


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """bytes=a-b | a- | -n → (start, end) включительно; None — нет заголовка; 'bad' — 416."""
    if not header:
        return None
    m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return "bad"
    a, b = m.group(1), m.group(2)
    if a == "":
        n = int(b)
        if n == 0:
            return "bad"
        return max(0, size - n), size - 1
    start = int(a)
    end = min(int(b), size - 1) if b else size - 1
    if start >= size or start > end:
        return "bad"
    return start, end


PLAYER_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>Sakura · YouTube</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}#p{position:absolute;inset:0;width:100%;height:100%;border:0}</style>
</head><body>
<iframe id="p" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen
  referrerpolicy="strict-origin-when-cross-origin"
  src="https://www.youtube.com/embed/__VIDEO__?enablejsapi=1&autoplay=1&start=__START__&origin=__ORIGIN__&widget_referrer=__ORIGIN__"></iframe>
<script>
// Мост к окну Sakura: только официальные методы YouTube IFrame API.
var player = null, parentOrigin = "*";
function post(msg){ try { window.parent.postMessage(Object.assign({source:"sakura-yt"}, msg), parentOrigin); } catch(e){} }
window.onYouTubeIframeAPIReady = function(){
  player = new YT.Player("p", { events: {
    onReady: function(){ post({event:"ready", duration: player.getDuration()}); },
    onStateChange: function(e){ post({event:"state", state:e.data, time: player.getCurrentTime(),
                                     duration: player.getDuration(), title: (player.getVideoData()||{}).title || ""}); },
    onError: function(e){ post({event:"error", code:e.data}); }
  }});
};
window.addEventListener("message", function(ev){
  var m = ev.data || {}; if (!player || m.target !== "sakura-yt") return;
  switch (m.cmd) {
    case "play": player.playVideo(); break;
    case "pause": player.pauseVideo(); break;
    case "toggle": (player.getPlayerState() === 1) ? player.pauseVideo() : player.playVideo(); break;
    case "seek": player.seekTo(Math.max(0, Number(m.time)||0), true); break;
    case "seekBy": player.seekTo(Math.max(0, player.getCurrentTime() + (Number(m.delta)||0)), true); break;
    case "rate": player.setPlaybackRate(Number(m.rate)||1); break;
    case "volume": player.setVolume(Math.max(0, Math.min(100, Number(m.volume)||0))); break;
    case "mute": player.isMuted() ? player.unMute() : player.mute(); break;
    case "load": player.loadVideoById({videoId: String(m.videoId||""), startSeconds: Number(m.start)||0}); break;
    case "status": post({event:"status", state: player.getPlayerState(), time: player.getCurrentTime(),
                         duration: player.getDuration(), rate: player.getPlaybackRate(),
                         title: (player.getVideoData()||{}).title || ""}); break;
  }
});
setInterval(function(){ if (player && player.getCurrentTime) post({event:"time", time: player.getCurrentTime()}); }, 1000);
</script>
<script src="https://www.youtube.com/iframe_api"></script>
</body></html>
"""


class MediaServer:
    def __init__(self, library, token: str | None = None):
        self.library = library
        self.token = token or secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self.port: int | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{self.origin}{path}{sep}t={self.token}"

    def player_url(self, video_id: str, start: int = 0) -> str:
        return self.url(f"/youtube/player.html?v={video_id}&start={int(start)}")

    def start(self, port: int = 0) -> int:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # без шума в логе; токен в URL не логируем
                pass

            def do_HEAD(self):
                self._serve(head=True)

            def do_GET(self):
                self._serve(head=False)

            def _deny(self, code: int, text: str = ""):
                body = text.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _serve(self, head: bool):
                host = (self.headers.get("Host") or "").lower()
                if host not in (f"127.0.0.1:{server.port}", f"localhost:{server.port}"):
                    return self._deny(403, "host")
                url = urlparse(self.path)
                qs = parse_qs(url.query)
                if not secrets.compare_digest((qs.get("t") or [""])[0], server.token):
                    return self._deny(401, "token")
                parts = [p for p in url.path.split("/") if p]
                try:
                    if len(parts) == 2 and parts[0] == "media":
                        return self._file(int(parts[1]), head)
                    if len(parts) == 2 and parts[0] == "cover" and re.fullmatch(r"[0-9a-f]{40}", parts[1]):
                        return self._cover(parts[1], head)
                    if len(parts) == 3 and parts[0] == "subtitle":
                        return self._subtitle(int(parts[1]), int(parts[2]), head)
                    if parts == ["youtube", "player.html"]:
                        return self._player(qs, head)
                except ValueError:
                    return self._deny(400, "bad id")
                return self._deny(404, "not found")

            def _headers(self, code: int, ctype: str, length: int, extra: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                # crossOrigin="anonymous" у <audio> нужен для Web Audio (AnalyserNode).
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()

            def _file(self, track_id: int, head: bool):
                t = server.library.get(track_id)
                if not t or not server.library.is_allowed(t["path"]) or not os.path.isfile(t["path"]):
                    return self._deny(404, "not found")
                path = t["path"]
                size = os.path.getsize(path)
                ext = os.path.splitext(path)[1].lower()
                ctype = MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
                rng = parse_range(self.headers.get("Range"), size)
                if rng == "bad":
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                start, end = rng if rng else (0, size - 1)
                length = max(0, end - start + 1)
                extra = {"Content-Range": f"bytes {start}-{end}/{size}"} if rng else None
                self._headers(206 if rng else 200, ctype, length, extra)
                if head or length == 0:
                    return None
                with open(path, "rb") as f:
                    f.seek(start)
                    left = length
                    try:
                        while left > 0:
                            buf = f.read(min(CHUNK, left))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            left -= len(buf)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # плеер перемотал и закрыл соединение
                return None

            def _cover(self, sha1: str, head: bool):
                p = os.path.join(server.library.cover_dir, sha1)
                if not os.path.isfile(p):
                    return self._deny(404, "not found")
                data = open(p, "rb").read()
                ctype = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                self._headers(200, ctype, len(data))
                if not head:
                    self.wfile.write(data)
                return None

            def _subtitle(self, track_id: int, n: int, head: bool):
                subs = server.library.subtitles(track_id)
                if not (0 <= n < len(subs)) or not server.library.is_allowed(subs[n]):
                    return self._deny(404, "not found")
                raw = open(subs[n], "rb").read().decode("utf-8", errors="replace")
                text = raw if subs[n].lower().endswith(".vtt") else srt_to_vtt(raw)
                body = text.encode("utf-8")
                self._headers(200, "text/vtt; charset=utf-8", len(body))
                if not head:
                    self.wfile.write(body)
                return None

            def _player(self, qs: dict, head: bool):
                vid = (qs.get("v") or [""])[0]
                if not YT_ID.fullmatch(vid):
                    return self._deny(400, "video id")
                start = (qs.get("start") or ["0"])[0]
                start = start if start.isdigit() else "0"
                body = (PLAYER_HTML.replace("__VIDEO__", vid).replace("__START__", start)
                        .replace("__ORIGIN__", html.escape(server.origin))).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head:
                    self.wfile.write(body)
                return None

        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="media-server", daemon=True).start()
        log.info("[media] http-сервер на 127.0.0.1:%s", self.port)
        return self.port

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
