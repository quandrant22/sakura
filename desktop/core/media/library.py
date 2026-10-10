"""desktop.core.media.library — медиатека на SQLite.

Сканирует выбранные владельцем папки (музыка и видео), читает теги и обложки
(mutagen), хранит треки, плейлисты, историю прослушивания и позиции видео.
Повторное сканирование трогает только изменённые файлы (mtime + размер) и
удаляет из базы исчезнувшие.
"""
import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable

log = logging.getLogger("sakura.media")

AUDIO_EXT = frozenset({".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma"})
VIDEO_EXT = frozenset({".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".ogv"})
SUBTITLE_EXT = (".vtt", ".srt")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,              -- audio | video
    folder TEXT NOT NULL,            -- корневая папка библиотеки
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    album_artist TEXT NOT NULL DEFAULT '',
    track_no INTEGER,
    year INTEGER,
    genre TEXT NOT NULL DEFAULT '',
    duration REAL,
    cover_hash TEXT                  -- sha1 обложки (кэш), NULL — нет
);
CREATE INDEX IF NOT EXISTS tracks_kind ON tracks(kind);
CREATE INDEX IF NOT EXISTS tracks_album ON tracks(album_artist, album);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    pos INTEGER NOT NULL,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    PRIMARY KEY (playlist_id, pos)
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY, track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    played_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS video_positions (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    position REAL NOT NULL, updated REAL NOT NULL
);
"""

TRACK_COLS = ("id", "path", "kind", "folder", "title", "artist", "album", "album_artist",
              "track_no", "year", "genre", "duration", "cover_hash")


def _first(tags, *keys) -> str:
    """Первое непустое значение тега (mutagen easy-теги — списки строк)."""
    if not tags:
        return ""
    for k in keys:
        v = tags.get(k)
        if v:
            v = v[0] if isinstance(v, list) else v
            s = str(v).strip()
            if s:
                return s
    return ""


def _int_prefix(s: str) -> int | None:
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def read_tags(path: str) -> dict:
    """Теги и длительность файла. Без mutagen или при ошибке — имя файла как название."""
    info = {"title": os.path.splitext(os.path.basename(path))[0], "artist": "", "album": "",
            "album_artist": "", "track_no": None, "year": None, "genre": "", "duration": None}
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
    except Exception as e:  # повреждённый файл не должен валить сканирование
        log.debug("[media] теги %s: %s", path, e)
        return info
    if f is None:
        return info
    if getattr(f, "info", None) is not None and getattr(f.info, "length", None):
        info["duration"] = round(float(f.info.length), 3)
    tags = f.tags
    info["title"] = _first(tags, "title") or info["title"]
    info["artist"] = _first(tags, "artist")
    info["album"] = _first(tags, "album")
    info["album_artist"] = _first(tags, "albumartist") or info["artist"]
    info["track_no"] = _int_prefix(_first(tags, "tracknumber"))
    info["year"] = _int_prefix(_first(tags, "date", "year"))
    info["genre"] = _first(tags, "genre")
    return info


def read_cover(path: str) -> bytes | None:
    """Встроенная обложка (ID3 APIC, FLAC picture, MP4 covr) или cover.jpg/folder.jpg рядом."""
    try:
        import mutagen
        f = mutagen.File(path)
        if f is not None:
            tags = getattr(f, "tags", None)
            if tags is not None:
                for key in list(tags.keys()):
                    if str(key).startswith("APIC"):
                        return tags[key].data
                if "covr" in tags and tags["covr"]:
                    return bytes(tags["covr"][0])
            pics = getattr(f, "pictures", None)
            if pics:
                return pics[0].data
    except Exception as e:
        log.debug("[media] обложка %s: %s", path, e)
    folder = os.path.dirname(path)
    for name in ("cover.jpg", "folder.jpg", "cover.png", "front.jpg"):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                return fh.read()
    return None


class MediaLibrary:
    def __init__(self, db_path: str, cover_dir: str | None = None):
        self.db_path = db_path
        self.cover_dir = cover_dir or os.path.join(os.path.dirname(db_path), "covers")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self.folders: dict[str, list[str]] = {"audio": [], "video": []}

    def close(self):
        with self._lock:
            self._db.close()

    # ── папки и безопасность пути ──────────────────────────────────
    def set_folders(self, audio: Iterable[str] = (), video: Iterable[str] = ()):
        self.folders = {"audio": [os.path.realpath(p) for p in audio],
                        "video": [os.path.realpath(p) for p in video]}

    def is_allowed(self, path: str) -> bool:
        """Файл внутри одной из выбранных папок (после разрешения .. и ссылок)."""
        real = os.path.realpath(path)
        for root in self.folders["audio"] + self.folders["video"]:
            try:
                if os.path.commonpath([real, root]) == root:
                    return True
            except ValueError:  # разные диски
                continue
        return False

    # ── сканирование ───────────────────────────────────────────────
    def scan(self, progress: Callable[[dict], None] | None = None) -> dict:
        """Инкрементальное сканирование всех папок. Возвращает счётчики."""
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "total": 0}
        files: list[tuple[str, str, str]] = []  # (path, kind, root)
        for kind, exts in (("audio", AUDIO_EXT), ("video", VIDEO_EXT)):
            for root in self.folders[kind]:
                for dirpath, _dirs, names in os.walk(root):
                    for n in names:
                        if os.path.splitext(n)[1].lower() in exts:
                            files.append((os.path.join(dirpath, n), kind, root))
        stats["total"] = len(files)
        with self._lock:
            known = {r["path"]: (r["mtime"], r["size"]) for r in
                     self._db.execute("SELECT path, mtime, size FROM tracks")}
        seen = set()
        for i, (path, kind, root) in enumerate(files, 1):
            seen.add(path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            old = known.get(path)
            if old and abs(old[0] - st.st_mtime) < 1e-6 and old[1] == st.st_size:
                stats["unchanged"] += 1
            else:
                self._upsert(path, kind, root, st)
                stats["updated" if old else "added"] += 1
            if progress and (i % 50 == 0 or i == len(files)):
                progress({"done": i, "total": len(files)})
        gone = [p for p in known if p not in seen]
        with self._lock:
            for p in gone:
                self._db.execute("DELETE FROM tracks WHERE path = ?", (p,))
            self._db.commit()
        stats["removed"] = len(gone)
        log.info("[media] сканирование: %s", stats)
        return stats

    def _upsert(self, path: str, kind: str, root: str, st: os.stat_result):
        t = read_tags(path) if kind == "audio" else {
            "title": os.path.splitext(os.path.basename(path))[0], "artist": "", "album": "",
            "album_artist": "", "track_no": None, "year": None, "genre": "", "duration": None}
        cover_hash = None
        if kind == "audio":
            data = read_cover(path)
            if data:
                cover_hash = hashlib.sha1(data).hexdigest()
                os.makedirs(self.cover_dir, exist_ok=True)
                cp = os.path.join(self.cover_dir, cover_hash)
                if not os.path.exists(cp):
                    with open(cp, "wb") as fh:
                        fh.write(data)
        with self._lock:
            self._db.execute(
                """INSERT INTO tracks (path, kind, folder, mtime, size, title, artist, album, album_artist,
                                       track_no, year, genre, duration, cover_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET kind=excluded.kind, folder=excluded.folder,
                     mtime=excluded.mtime, size=excluded.size, title=excluded.title, artist=excluded.artist,
                     album=excluded.album, album_artist=excluded.album_artist, track_no=excluded.track_no,
                     year=excluded.year, genre=excluded.genre, duration=excluded.duration,
                     cover_hash=excluded.cover_hash""",
                (path, kind, root, st.st_mtime, st.st_size, t["title"], t["artist"], t["album"],
                 t["album_artist"], t["track_no"], t["year"], t["genre"], t["duration"], cover_hash))

    def clear_cover_cache(self) -> int:
        n = 0
        if os.path.isdir(self.cover_dir):
            for name in os.listdir(self.cover_dir):
                os.remove(os.path.join(self.cover_dir, name))
                n += 1
        with self._lock:
            self._db.execute("UPDATE tracks SET cover_hash = NULL")
            self._db.commit()
        return n

    # ── чтение ─────────────────────────────────────────────────────
    def _rows(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args)]

    def get(self, track_id: int) -> dict | None:
        rows = self._rows(f"SELECT {', '.join(TRACK_COLS)} FROM tracks WHERE id = ?", (track_id,))
        return rows[0] if rows else None

    def count(self, kind: str = "audio") -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM tracks WHERE kind = ?", (kind,)).fetchone()[0]

    def tracks(self, kind: str = "audio", offset: int = 0, limit: int = 200,
               album: str | None = None, artist: str | None = None) -> list[dict]:
        where, args = ["kind = ?"], [kind]
        if album is not None:
            where.append("album = ?")
            args.append(album)
        if artist is not None:
            where.append("(artist = ? OR album_artist = ?)")
            args += [artist, artist]
        order = ("album_artist COLLATE NOCASE, album COLLATE NOCASE, track_no, title COLLATE NOCASE"
                 if kind == "audio" else "folder, path COLLATE NOCASE")
        return self._rows(f"SELECT {', '.join(TRACK_COLS)} FROM tracks WHERE {' AND '.join(where)} "
                          f"ORDER BY {order} LIMIT ? OFFSET ?", (*args, limit, offset))

    def search(self, q: str, kind: str = "audio", limit: int = 100) -> list[dict]:
        like = f"%{q.strip().lower()}%"
        # LOWER() SQLite не знает кириллицу — сравниваем в Python по уже отобранному.
        rows = self._rows(f"SELECT {', '.join(TRACK_COLS)} FROM tracks WHERE kind = ?", (kind,))
        needle = like.strip("%")
        out = [r for r in rows
               if needle in f"{r['title']} {r['artist']} {r['album']}".lower()]
        return out[:limit]

    def albums(self) -> list[dict]:
        return self._rows("""SELECT album, album_artist, COUNT(*) AS tracks, MAX(year) AS year,
                                    MAX(cover_hash) AS cover_hash, SUM(duration) AS duration
                             FROM tracks WHERE kind='audio' AND album != ''
                             GROUP BY album_artist, album ORDER BY album_artist COLLATE NOCASE, year""")

    def artists(self) -> list[dict]:
        return self._rows("""SELECT album_artist AS artist, COUNT(*) AS tracks, COUNT(DISTINCT album) AS albums
                             FROM tracks WHERE kind='audio' AND album_artist != ''
                             GROUP BY album_artist ORDER BY album_artist COLLATE NOCASE""")

    def folder_siblings(self, track_id: int) -> list[dict]:
        """Плейлист папки для видео: файлы того же каталога по имени."""
        t = self.get(track_id)
        if not t:
            return []
        rows = self._rows(f"SELECT {', '.join(TRACK_COLS)} FROM tracks WHERE kind = ? ORDER BY path COLLATE NOCASE",
                          (t["kind"],))
        d = os.path.dirname(t["path"])
        return [r for r in rows if os.path.dirname(r["path"]) == d]

    def subtitles(self, track_id: int) -> list[str]:
        t = self.get(track_id)
        if not t:
            return []
        base = os.path.splitext(t["path"])[0]
        d = os.path.dirname(t["path"])
        out = []
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if name.lower().endswith(SUBTITLE_EXT) and os.path.splitext(p)[0].startswith(base):
                out.append(p)
        return out

    # ── плейлисты ──────────────────────────────────────────────────
    def playlist_create(self, name: str, track_ids: Iterable[int] = ()) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO playlists (name, created) VALUES (?, ?)", (name, time.time()))
            pid = cur.lastrowid
            self._db.executemany("INSERT INTO playlist_items (playlist_id, pos, track_id) VALUES (?,?,?)",
                                 [(pid, i, t) for i, t in enumerate(track_ids)])
            self._db.commit()
        return pid

    def playlist_set(self, pid: int, track_ids: Iterable[int]):
        with self._lock:
            self._db.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
            self._db.executemany("INSERT INTO playlist_items (playlist_id, pos, track_id) VALUES (?,?,?)",
                                 [(pid, i, t) for i, t in enumerate(track_ids)])
            self._db.commit()

    def playlist_delete(self, pid: int):
        with self._lock:
            self._db.execute("DELETE FROM playlists WHERE id = ?", (pid,))
            self._db.commit()

    def playlists(self) -> list[dict]:
        return self._rows("""SELECT p.id, p.name, COUNT(i.track_id) AS tracks FROM playlists p
                             LEFT JOIN playlist_items i ON i.playlist_id = p.id GROUP BY p.id ORDER BY p.name""")

    def playlist_tracks(self, pid: int) -> list[dict]:
        cols = ", ".join(f"t.{c}" for c in TRACK_COLS)
        return self._rows(f"SELECT {cols} FROM playlist_items i JOIN tracks t ON t.id = i.track_id "
                          "WHERE i.playlist_id = ? ORDER BY i.pos", (pid,))

    # ── история и позиции ──────────────────────────────────────────
    def add_history(self, track_id: int):
        with self._lock:
            self._db.execute("INSERT INTO history (track_id, played_at) VALUES (?, ?)", (track_id, time.time()))
            self._db.commit()

    def history(self, limit: int = 50) -> list[dict]:
        cols = ", ".join(f"t.{c}" for c in TRACK_COLS)
        return self._rows(f"SELECT {cols}, h.played_at FROM history h JOIN tracks t ON t.id = h.track_id "
                          "ORDER BY h.played_at DESC LIMIT ?", (limit,))

    def set_position(self, track_id: int, position: float):
        with self._lock:
            self._db.execute("INSERT INTO video_positions (track_id, position, updated) VALUES (?,?,?) "
                             "ON CONFLICT(track_id) DO UPDATE SET position=excluded.position, updated=excluded.updated",
                             (track_id, float(position), time.time()))
            self._db.commit()

    def get_position(self, track_id: int) -> float:
        with self._lock:
            r = self._db.execute("SELECT position FROM video_positions WHERE track_id = ?", (track_id,)).fetchone()
        return float(r[0]) if r else 0.0
