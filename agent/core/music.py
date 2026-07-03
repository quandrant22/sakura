"""
core/music.py — полная интеграция с Яндекс Музыкой + SMTC (агент).

Два источника данных:
  - SMTC (winsdk)       — что играет прямо сейчас, статус, прогресс, управление
  - yandex-music-api    — история, лайк/дизлайк, плейлисты, рекомендации, поиск

Команды (action в WS от VPS):
  music_info            — текущий трек (название, исполнитель, статус, прогресс)
  music_play_pause      — play/pause через SMTC
  music_next            — следующий трек через SMTC
  music_prev            — предыдущий трек через SMTC
  music_like            — лайк текущего трека через API
  music_dislike         — дизлайк текущего трека через API
  music_history         — последние 10 треков
  music_playlists       — список плейлистов
  music_liked_tracks    — любимые треки (топ-20)
  music_recommendations — рекомендации («моя волна»)
  music_search:<query>  — поиск треков

Зависимости (на агенте):
  pip install winsdk yandex-music
"""

import asyncio
import logging
from typing import Optional

log = logging.getLogger("sakura.music")

YM_TOKEN = "y0__xD-vJT9AxjBmigg4P3cnRK-d-6FQFiNbmiqOwneUJlqXAj2kA"

# ── SMTC — системный медиа-интерфейс Windows ─────────────────────────

async def _smtc_get_info() -> Optional[dict]:
    """Возвращает текущий трек и статус через Windows SMTC."""
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        )

        sessions = await MediaManager.request_async()
        session  = sessions.get_current_session()
        if not session:
            return None

        props    = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        playback = session.get_playback_info()

        status_map = {
            PlaybackStatus.PLAYING:  "играет",
            PlaybackStatus.PAUSED:   "пауза",
            PlaybackStatus.STOPPED:  "остановлен",
            PlaybackStatus.CHANGING: "переключение",
            PlaybackStatus.CLOSED:   "закрыт",
        }
        status = status_map.get(playback.playback_status, "неизвестно")

        # Прогресс в секундах
        try:
            pos_s  = timeline.position.total_seconds()
            end_s  = timeline.end_time.total_seconds()
            pct    = int(pos_s / end_s * 100) if end_s > 0 else 0
            dur    = f"{int(end_s // 60)}:{int(end_s % 60):02d}"
            cur    = f"{int(pos_s // 60)}:{int(pos_s % 60):02d}"
        except Exception:
            pos_s = end_s = pct = 0
            dur = cur = "?:??"

        return {
            "title":    props.title or "",
            "artist":   props.artist or "",
            "album":    props.album_title or "",
            "status":   status,
            "position": cur,
            "duration": dur,
            "progress": pct,
        }
    except Exception as e:
        log.debug(f"[music] SMTC: {e}")
        return None


def get_current_track() -> dict:
    """Синхронная обёртка для получения текущего трека (из контекста агента)."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_smtc_get_info(), loop)
            return future.result(timeout=1.0) or {}
        else:
            return loop.run_until_complete(_smtc_get_info()) or {}
    except Exception:
        return {}


async def _smtc_control(action: str) -> bool:
    """Управление воспроизведением через SMTC."""
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )
        sessions = await MediaManager.request_async()
        session  = sessions.get_current_session()
        if not session:
            return False

        if action == "play_pause":
            await session.try_toggle_play_pause_async()
        elif action == "next":
            await session.try_skip_next_async()
        elif action == "prev":
            await session.try_skip_previous_async()
        else:
            return False
        return True
    except Exception as e:
        log.debug(f"[music] SMTC control {action}: {e}")
        return False


# ── Яндекс Музыка API ─────────────────────────────────────────────────

_ym_client = None


def _get_ym_client():
    global _ym_client
    if _ym_client is None:
        from yandex_music import Client
        _ym_client = Client(YM_TOKEN).init()
    return _ym_client


def _ym_like_current(title: str, artist: str) -> dict:
    """Лайкает трек по названию и исполнителю через прямой API-вызов."""
    try:
        client  = _get_ym_client()
        results = client.search(f"{artist} {title}", type_="track")
        if not results or not results.tracks or not results.tracks.results:
            return {"ok": False, "result": "Трек не найден в Яндекс Музыке"}
        track = results.tracks.results[0]
        uid   = client.me.account.uid
        client._request.post(
            f"https://api.music.yandex.net/users/{uid}/likes/tracks/add-multiple",
            {"track-ids": str(track.id)},
        )
        artist_name = track.artists[0].name if track.artists else artist
        return {"ok": True, "result": f"Лайк: {artist_name} — {track.title}"}
    except Exception as e:
        log.error(f"[music] like: {e}")
        return {"ok": False, "result": str(e)}


def _ym_dislike_current(title: str, artist: str) -> dict:
    """Дизлайкает трек через прямой API-вызов."""
    try:
        client  = _get_ym_client()
        results = client.search(f"{artist} {title}", type_="track")
        if not results or not results.tracks or not results.tracks.results:
            return {"ok": False, "result": "Трек не найден"}
        track = results.tracks.results[0]
        uid   = client.me.account.uid
        client._request.post(
            f"https://api.music.yandex.net/users/{uid}/dislikes/tracks/add-multiple",
            {"track-ids": str(track.id)},
        )
        artist_name = track.artists[0].name if track.artists else artist
        return {"ok": True, "result": f"Дизлайк: {artist_name} — {track.title}"}
    except Exception as e:
        log.error(f"[music] dislike: {e}")
        return {"ok": False, "result": str(e)}


def _ym_history() -> dict:
    """История прослушивания — последние лайкнутые треки по timestamp."""
    try:
        client = _get_ym_client()
        liked  = client.users_likes_tracks()
        recent = sorted(
            liked.tracks or [],
            key=lambda t: getattr(t, "timestamp", ""),
            reverse=True
        )[:10]
        tracks = []
        for lt in recent:
            try:
                ft     = lt.fetch_track()
                artist = ft.artists[0].name if ft.artists else "?"
                ts     = getattr(lt, "timestamp", "")[:10]  # только дата
                tracks.append(f"{artist} — {ft.title} ({ts})")
            except Exception:
                pass
        return {"ok": True, "tracks": tracks}
    except Exception as e:
        log.error(f"[music] history: {e}")
        return {"ok": False, "tracks": [], "result": str(e)}


def _ym_playlists() -> dict:
    """Список плейлистов пользователя."""
    try:
        client    = _get_ym_client()
        playlists = client.users_playlists_list()
        result    = []
        for p in (playlists or [])[:15]:
            result.append({
                "title":    p.title or "Без названия",
                "kind":     p.kind,
                "count":    p.track_count or 0,
            })
        return {"ok": True, "playlists": result}
    except Exception as e:
        log.error(f"[music] playlists: {e}")
        return {"ok": False, "playlists": [], "result": str(e)}


def _ym_liked_tracks() -> dict:
    """Любимые треки."""
    try:
        client = _get_ym_client()
        liked  = client.users_likes_tracks()
        tracks = []
        for lt in (liked.tracks or [])[:20]:
            t = lt.fetch_track() if hasattr(lt, 'fetch_track') else lt
            if hasattr(t, 'title') and t.title:
                artist = t.artists[0].name if t.artists else "?"
                tracks.append(f"{artist} — {t.title}")
        return {"ok": True, "tracks": tracks}
    except Exception as e:
        log.error(f"[music] liked: {e}")
        return {"ok": False, "tracks": [], "result": str(e)}


def _ym_recommendations() -> dict:
    """Рекомендации — треки из Моей волны."""
    try:
        client = _get_ym_client()
        # Моя волна через радио
        station_result = client.rotor_station_tracks("user:onyourwave")
        tracks = []
        for seq in (getattr(station_result, 'sequence', None) or [])[:10]:
            t = seq.track
            if hasattr(t, 'title') and t.title:
                artist = t.artists[0].name if t.artists else "?"
                tracks.append(f"{artist} — {t.title}")
        return {"ok": True, "tracks": tracks}
    except Exception as e:
        log.error(f"[music] recommendations: {e}")
        return {"ok": False, "tracks": [], "result": str(e)}


def _ym_search(query: str) -> dict:
    """Поиск треков."""
    try:
        client  = _get_ym_client()
        results = client.search(query, type_="track")
        tracks  = []
        if results and results.tracks:
            for t in results.tracks.results[:8]:
                artist = t.artists[0].name if t.artists else "?"
                tracks.append({
                    "title":  t.title,
                    "artist": artist,
                    "album":  t.albums[0].title if t.albums else "",
                    "id":     t.id,
                })
        return {"ok": True, "tracks": tracks}
    except Exception as e:
        log.error(f"[music] search: {e}")
        return {"ok": False, "tracks": [], "result": str(e)}


def _enrich_with_ym(title: str, artist: str) -> dict:
    """Ищет трек в YM и возвращает обогащённые метаданные."""
    try:
        client  = _get_ym_client()
        results = client.search(f"{artist} {title}", type_="track")
        if results and results.tracks and results.tracks.results:
            track = results.tracks.results[0]
            cover_url = ""
            try:
                cover_url = track.get_cover_url(size="400x400") or ""
            except Exception:
                pass
            if not cover_url and track.cover_uri:
                cover_url = "https://" + track.cover_uri.replace("%%", "400x400")
            album_title = track.albums[0].title if track.albums else ""
            album_year = getattr(track.albums[0], "year", None) if track.albums else None
            genre = getattr(track.albums[0], "genre", "") or "" if track.albums else ""
            return {
                "cover_url":  cover_url,
                "genre":      genre,
                "album":      album_title,
                "album_year": album_year,
                "track_id":   str(track.id) if track.id else "",
                "artists":    [a.name for a in (track.artists or [])],
            }
    except Exception as e:
        log.debug(f"[music] enrich: {e}")
    return {}


def _ym_play_track(query: str) -> dict:
    """Ищет трек в YM и запускает его."""
    try:
        client  = _get_ym_client()
        results = client.search(query, type_="track")
        if not results or not results.tracks or not results.tracks.results:
            return {"ok": False, "result": f"Трек «{query}» не найден"}
        track = results.tracks.results[0]
        client.play([track.id], position=0)
        artist = track.artists[0].name if track.artists else "?"
        return {"ok": True, "result": f"Играет: {artist} — {track.title}"}
    except Exception as e:
        log.error(f"[music] play_track: {e}")
        return {"ok": False, "result": str(e)}


def _ym_play_playlist(kind: str) -> dict:
    """Запускает плейлист по kind или названию."""
    try:
        client = _get_ym_client()
        uid    = client.me.account.uid
        if kind.isdigit():
            playlist = client.users_playlists(int(kind), uid)
        else:
            playlists = client.users_playlists_list()
            playlist  = None
            for p in (playlists or []):
                if kind.lower() in (p.title or "").lower():
                    playlist = p
                    break
            if not playlist:
                return {"ok": False, "result": f"Плейлист «{kind}» не найден"}
            playlist = client.users_playlists(playlist.kind, uid)
        tracks = playlist.fetch_tracks()
        if not tracks:
            return {"ok": False, "result": "Плейлист пуст"}
        track_ids = [str(t.id) for t in tracks if t.id]
        client.play(track_ids, position=0)
        return {"ok": True, "result": f"Плейлист «{playlist.title}»: {len(track_ids)} треков"}
    except Exception as e:
        log.error(f"[music] play_playlist: {e}")
        return {"ok": False, "result": str(e)}


def _ym_play_wave() -> dict:
    """Запускает «Мою волну»."""
    try:
        client      = _get_ym_client()
        tracks_seq  = client.rotor_station_tracks("user:onyourwave")
        track_ids   = []
        for seq in (getattr(tracks_seq, 'sequence', None) or [])[:50]:
            t = seq.track
            if hasattr(t, 'id') and t.id:
                track_ids.append(str(t.id))
        if not track_ids:
            return {"ok": False, "result": "Моя волна пуста"}
        client.play(track_ids, position=0)
        return {"ok": True, "result": f"Моя волна: {len(track_ids)} треков"}
    except Exception as e:
        log.error(f"[music] play_wave: {e}")
        return {"ok": False, "result": str(e)}


# ── Точка входа ───────────────────────────────────────────────────────

async def music_command(action: str) -> dict:
    """
    Вызывается из agent._run_command для всех music_* команд.
    Возвращает dict который агент отправляет на VPS как command_result.
    """

    # ── SMTC команды ─────────────────────────────────────────────────
    if action == "music_info":
        info = await _smtc_get_info()
        if not info or not info.get("title"):
            return {"ok": False, "result": "Ничего не играет"}
        # Обогащаем через YM API (обложка, жанр, год, track_id)
        try:
            ym = await asyncio.to_thread(_enrich_with_ym, info["artist"], info["title"])
            if ym:
                info["cover_url"]  = ym.get("cover_url", "")
                info["genre"]      = ym.get("genre", "")
                info["album_year"] = ym.get("album_year")
                info["track_id"]   = ym.get("track_id", "")
                info["artists"]    = ym.get("artists", [info["artist"]])
                if ym.get("album") and not info.get("album"):
                    info["album"] = ym["album"]
        except Exception:
            pass
        result = f"{info['artist']} — {info['title']}"
        if info['status'] != "играет":
            result += f" ({info['status']})"
        if info.get('duration') and info['duration'] != "?:??":
            result += f" [{info.get('position', '?:??')} / {info['duration']}]"
        return {"ok": True, "result": result, "info": info}

    if action in ("music_play_pause", "music_next", "music_prev"):
        ctrl = action.replace("music_", "")
        ok   = await _smtc_control(ctrl)
        labels = {"play_pause": "play/pause", "next": "следующий", "prev": "предыдущий"}
        return {"ok": ok, "result": labels.get(ctrl, ctrl) if ok else "Нет активного плеера"}

    # ── API команды (в потоке — синхронные) ──────────────────────────
    if action == "music_like":
        info = await _smtc_get_info()
        if not info or not info.get("title"):
            return {"ok": False, "result": "Неизвестно что играет"}
        return await asyncio.to_thread(_ym_like_current, info["title"], info["artist"])

    if action == "music_dislike":
        info = await _smtc_get_info()
        if not info or not info.get("title"):
            return {"ok": False, "result": "Неизвестно что играет"}
        return await asyncio.to_thread(_ym_dislike_current, info["title"], info["artist"])

    if action == "music_history":
        return await asyncio.to_thread(_ym_history)

    if action == "music_playlists":
        return await asyncio.to_thread(_ym_playlists)

    if action == "music_liked_tracks":
        return await asyncio.to_thread(_ym_liked_tracks)

    if action == "music_recommendations":
        return await asyncio.to_thread(_ym_recommendations)

    if action.startswith("music_search:"):
        query = action[len("music_search:"):]
        return await asyncio.to_thread(_ym_search, query)

    # ── YM API: воспроизведение ──────────────────────────────────────
    if action.startswith("music_play_track:"):
        query = action[len("music_play_track:"):]
        return await asyncio.to_thread(_ym_play_track, query)

    if action.startswith("music_play_playlist:"):
        kind = action[len("music_play_playlist:"):]
        return await asyncio.to_thread(_ym_play_playlist, kind)

    if action == "music_play_wave":
        return await asyncio.to_thread(_ym_play_wave)

    return {"ok": False, "result": f"Неизвестная музыкальная команда: {action}"}