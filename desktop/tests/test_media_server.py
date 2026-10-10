"""media_server: токен, Host, Range (206/416), path traversal, обложки, субтитры, YouTube-страница."""
import http.client
import os

import pytest

from desktop.core.media.library import MediaLibrary
from desktop.core.media.media_server import MediaServer, parse_range, srt_to_vtt
from desktop.tests.media_fixtures import PNG_1PX, make_mp3


@pytest.fixture
def server(tmp_path):
    music = tmp_path / "music"
    make_mp3(music / "a.mp3", title="A", cover=PNG_1PX)
    vid = tmp_path / "video"
    vid.mkdir()
    (vid / "clip.mp4").write_bytes(bytes(range(256)) * 4)  # 1024 байта
    (vid / "clip.srt").write_text("1\n00:00:01,500 --> 00:00:02,000\nПривет\n", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("секрет", encoding="utf-8")
    lib = MediaLibrary(str(tmp_path / "data" / "media.db"))
    lib.set_folders(audio=[str(music)], video=[str(vid)])
    lib.scan()
    srv = MediaServer(lib, token="tok")
    srv.start()
    yield srv, lib, tmp_path
    srv.stop()
    lib.close()


def get(srv, path, headers=None, method="GET", host=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{srv.port}", **(headers or {})}
    c.request(method, path, headers=h)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r, body


def vid_id(lib):
    return lib.tracks("video")[0]["id"]


def test_token_required(server):
    srv, lib, _ = server
    r, _ = get(srv, f"/media/{vid_id(lib)}")
    assert r.status == 401
    r, _ = get(srv, f"/media/{vid_id(lib)}?t=wrong")
    assert r.status == 401
    r, body = get(srv, f"/media/{vid_id(lib)}?t=tok")
    assert r.status == 200 and len(body) == 1024 and r.getheader("Accept-Ranges") == "bytes"


def test_foreign_host_rejected(server):
    srv, lib, _ = server
    r, _ = get(srv, f"/media/{vid_id(lib)}?t=tok", host="evil.example:80")
    assert r.status == 403


def test_range_requests(server):
    srv, lib, _ = server
    path = f"/media/{vid_id(lib)}?t=tok"
    r, body = get(srv, path, {"Range": "bytes=10-19"})
    assert r.status == 206 and body == bytes(range(10, 20))
    assert r.getheader("Content-Range") == "bytes 10-19/1024"
    r, body = get(srv, path, {"Range": "bytes=1000-"})
    assert r.status == 206 and len(body) == 24
    r, body = get(srv, path, {"Range": "bytes=-4"})
    assert body == bytes([252, 253, 254, 255])
    r, _ = get(srv, path, {"Range": "bytes=5000-6000"})
    assert r.status == 416 and r.getheader("Content-Range") == "bytes */1024"
    r, body = get(srv, path, method="HEAD")
    assert r.status == 200 and body == b"" and r.getheader("Content-Length") == "1024"


def test_content_types(server):
    srv, lib, _ = server
    r, _ = get(srv, f"/media/{lib.tracks('audio')[0]['id']}?t=tok")
    assert r.getheader("Content-Type") == "audio/mpeg"
    assert r.getheader("Access-Control-Allow-Origin") == "*"
    r, _ = get(srv, f"/media/{vid_id(lib)}?t=tok")
    assert r.getheader("Content-Type") == "video/mp4"


def test_path_traversal_and_unknown(server):
    srv, lib, tmp = server
    for p in ("/media/../secret.txt?t=tok", "/media/%2e%2e%2fsecret.txt?t=tok", "/media/99999?t=tok",
              "/cover/..%2f..%2fsecret.txt?t=tok", "/etc/passwd?t=tok"):
        r, body = get(srv, p)
        assert r.status in (400, 404), p
        assert "секрет".encode() not in body


def test_file_moved_outside_folders_not_served(server):
    srv, lib, tmp = server
    t = lib.tracks("video")[0]
    lib.set_folders(audio=[], video=[str(tmp / "elsewhere")])  # папку убрали из библиотеки
    r, _ = get(srv, f"/media/{t['id']}?t=tok")
    assert r.status == 404


def test_cover_and_subtitles(server):
    srv, lib, _ = server
    t = lib.tracks("audio")[0]
    r, body = get(srv, f"/cover/{t['cover_hash']}?t=tok")
    assert r.status == 200 and body == PNG_1PX and r.getheader("Content-Type") == "image/png"
    r, body = get(srv, f"/subtitle/{vid_id(lib)}/0?t=tok")
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/vtt")
    assert body.decode("utf-8").startswith("WEBVTT") and "00:00:01.500" in body.decode("utf-8")
    r, _ = get(srv, f"/subtitle/{vid_id(lib)}/5?t=tok")
    assert r.status == 404


def test_youtube_player_page(server):
    srv, _, _ = server
    r, body = get(srv, "/youtube/player.html?v=dQw4w9WgXcQ&start=42&t=tok")
    text = body.decode("utf-8")
    assert r.status == 200 and r.getheader("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in text
    assert f"embed/dQw4w9WgXcQ?enablejsapi=1&autoplay=1&start=42&origin=http://127.0.0.1:{srv.port}" in text
    assert "https://www.youtube.com/iframe_api" in text
    r, _ = get(srv, "/youtube/player.html?v=<script>&t=tok")
    assert r.status == 400


def test_urls(server):
    srv, _, _ = server
    assert srv.url("/media/1") == f"http://127.0.0.1:{srv.port}/media/1?t=tok"
    assert srv.player_url("abcdefghijk", 5).endswith("player.html?v=abcdefghijk&start=5&t=tok")


@pytest.mark.parametrize("hdr,expected", [
    (None, None), ("bytes=0-9", (0, 9)), ("bytes=5-", (5, 99)), ("bytes=-10", (90, 99)),
    ("bytes=0-500", (0, 99)), ("bytes=100-", "bad"), ("bytes=9-5", "bad"), ("bytes=-0", "bad"),
    ("items=0-1", "bad"), ("bytes=-", "bad"),
])
def test_parse_range(hdr, expected):
    assert parse_range(hdr, 100) == expected


def test_srt_to_vtt():
    assert srt_to_vtt("﻿1\r\n00:00:01,000 --> 00:00:02,250\r\nx\r\n") == \
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.250\nx\n"


def test_no_symlink_escape(server, tmp_path):
    srv, lib, tmp = server
    link = tmp / "video" / "link.mp4"
    try:
        os.symlink(tmp / "secret.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("симлинки недоступны без прав")
    lib.scan()
    t = next((x for x in lib.tracks("video") if x["path"].endswith("link.mp4")), None)
    if t:
        r, body = get(srv, f"/media/{t['id']}?t=tok")
        assert r.status == 404 and "секрет".encode() not in body
