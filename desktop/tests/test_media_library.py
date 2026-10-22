"""Медиатека: сканер на сгенерированных wav/mp3/flac, теги, обложки, поиск,
инкрементальность, плейлисты, история, позиции видео, проверка пути."""
import os
import time

import pytest

from desktop.core.media import library as lib
from desktop.tests.media_fixtures import PNG_1PX, make_flac, make_mp3, make_wav


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "music"
    make_mp3(root / "Artist A" / "Album X" / "01.mp3", title="Первая", artist="Artist A",
             album="Album X", track="1/10", cover=PNG_1PX)
    make_mp3(root / "Artist A" / "Album X" / "02.mp3", title="Вторая", artist="Artist A",
             album="Album X", track=2)
    make_flac(root / "Б" / "song.flac", title="Ёлка", artist="Б-группа", album="Зима",
              tracknumber=3, date="2024-01-01", genre="Поп")
    make_wav(root / "loose.wav")
    (root / "notes.txt").write_text("не медиа", encoding="utf-8")
    return root


@pytest.fixture
def videos(tmp_path):
    root = tmp_path / "video"
    root.mkdir()
    for n in ("b.mp4", "a.webm", "c.mkv"):
        (root / n).write_bytes(b"\x00" * 64)
    (root / "a.ru.vtt").write_text("WEBVTT\n", encoding="utf-8")
    (root / "a.en.srt").write_text("1\n", encoding="utf-8")
    return root


@pytest.fixture
def library(tmp_path, music, videos):
    m = lib.MediaLibrary(str(tmp_path / "data" / "media.db"))
    m.set_folders(audio=[str(music)], video=[str(videos)])
    yield m
    m.close()


def test_scan_reads_tags_and_durations(library):
    stats = library.scan()
    assert stats == {"added": 7, "updated": 0, "removed": 0, "unchanged": 0, "total": 7}
    tracks = {t["title"]: t for t in library.tracks("audio")}
    assert set(tracks) == {"Первая", "Вторая", "Ёлка", "loose"}
    first = tracks["Первая"]
    assert (first["artist"], first["album"], first["track_no"]) == ("Artist A", "Album X", 1)
    assert first["duration"] and 0.9 < first["duration"] < 1.2
    elka = tracks["Ёлка"]
    assert (elka["year"], elka["genre"], elka["track_no"]) == (2024, "Поп", 3)
    assert 1.9 < elka["duration"] < 2.1
    assert tracks["loose"]["duration"] == pytest.approx(0.5, abs=0.01)
    assert library.count("video") == 3


def test_cover_cached_by_hash(library):
    library.scan()
    first = next(t for t in library.tracks() if t["title"] == "Первая")
    assert first["cover_hash"]
    assert os.path.isfile(os.path.join(library.cover_dir, first["cover_hash"]))
    assert library.clear_cover_cache() == 1
    assert all(t["cover_hash"] is None for t in library.tracks())


def test_rescan_only_changed_and_removes_missing(library, music):
    library.scan()
    path = music / "Artist A" / "Album X" / "02.mp3"
    make_mp3(path, title="Вторая (ремастер)", artist="Artist A", album="Album X", track=2)
    os.utime(path, (time.time() + 5, time.time() + 5))
    os.remove(music / "loose.wav")
    stats = library.scan()
    assert (stats["updated"], stats["removed"], stats["unchanged"], stats["added"]) == (1, 1, 5, 0)
    assert "Вторая (ремастер)" in {t["title"] for t in library.tracks()}


def test_scan_progress_reported(library):
    seen = []
    library.scan(progress=seen.append)
    assert seen[-1] == {"done": 7, "total": 7}


def test_search_cyrillic_case_insensitive(library):
    library.scan()
    assert [t["title"] for t in library.search("ёлк")] == ["Ёлка"]
    assert {t["title"] for t in library.search("album x")} == {"Первая", "Вторая"}
    assert library.search("нет такого") == []


def test_views_albums_artists(library):
    library.scan()
    albums = {(a["album_artist"], a["album"]): a["tracks"] for a in library.albums()}
    assert albums == {("Artist A", "Album X"): 2, ("Б-группа", "Зима"): 1}
    artists = {a["artist"]: a["albums"] for a in library.artists()}
    assert artists == {"Artist A": 1, "Б-группа": 1}
    assert [t["track_no"] for t in library.tracks(album="Album X")] == [1, 2]


def test_playlists_and_history(library):
    library.scan()
    ids = [t["id"] for t in library.tracks()]
    pid = library.playlist_create("Утро", ids[:2])
    assert library.playlists() == [{"id": pid, "name": "Утро", "tracks": 2}]
    library.playlist_set(pid, list(reversed(ids[:2])))
    assert [t["id"] for t in library.playlist_tracks(pid)] == list(reversed(ids[:2]))
    library.add_history(ids[0])
    assert library.history()[0]["id"] == ids[0]
    library.playlist_delete(pid)
    assert library.playlists() == []


def test_video_folder_playlist_positions_subtitles(library):
    library.scan()
    vids = library.tracks("video")
    assert [os.path.basename(v["path"]) for v in vids] == ["a.webm", "b.mp4", "c.mkv"]
    a = vids[0]
    assert [os.path.basename(v["path"]) for v in library.folder_siblings(a["id"])] == ["a.webm", "b.mp4", "c.mkv"]
    assert library.get_position(a["id"]) == 0.0
    library.set_position(a["id"], 61.5)
    assert library.get_position(a["id"]) == 61.5
    assert [os.path.basename(s) for s in library.subtitles(a["id"])] == ["a.en.srt", "a.ru.vtt"]


def test_is_allowed_blocks_traversal(library, music, tmp_path):
    inside = music / "Artist A" / "Album X" / "01.mp3"
    assert library.is_allowed(str(inside))
    assert not library.is_allowed(str(music / ".." / "data" / "media.db"))
    assert not library.is_allowed(str(tmp_path / "elsewhere.mp3"))
    assert not library.is_allowed("C:\\Windows\\win.ini")


def test_broken_file_does_not_break_scan(library, music):
    (music / "broken.mp3").write_bytes(b"not an mp3 at all")
    stats = library.scan()
    assert stats["added"] == 8
    assert "broken" in {t["title"] for t in library.tracks()}
