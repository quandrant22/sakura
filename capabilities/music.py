"""Домен «музыка» (этап 3): все действия executor=agent.

Бэкенд (SMTC / браузер / приложение) выбирает агент по каноническому id —
на провод уходит только канонический id, без легаси-написаний и без
таблицы перевода в agent/core/agent.py.
"""

import re

from sakura_core.executor import AgentCommand, register_table
from sakura_core.ru_numbers import digits_in, volume_step

# 20 музыкальных действий реестра (music.*, без music_stats.*)
MUSIC_AGENT_ACTIONS = (
    "music.next", "music.prev", "music.restart", "music.play_pause", "music.like",
    "music.dislike", "music.now_playing", "music.history",
    "music.liked_tracks", "music.playlists", "music.shuffle", "music.repeat",
    "music.seek_forward", "music.seek_back", "music.podcasts", "music.mute",
    "music.volume_up", "music.volume_down", "music.wave", "music.play_track",
)

# Явная таблица: канонический id → команда агенту.
MUSIC_COMMANDS = {aid: AgentCommand(aid) for aid in MUSIC_AGENT_ACTIONS}
# Алиасы реестра (другой context) — тот же id на проводе.
MUSIC_COMMANDS["music.restart_playing"] = AgentCommand("music.restart")

# Действия с параметром: на провод уходит канонический id и текст запроса.
MUSIC_QUERY_ACTIONS = (
    "music.play_artist", "music.play_album", "music.play_playlist", "music.station", "music.queue_add",
    "music.play_next", "music.queue_remove", "music.search", "music.playlist_add", "music.playlist_remove",
    "music.playlist_create", "music.playlist_delete", "music.seek_to", "music.volume_set",
)
# Без параметра: всё берётся из текущего трека.
MUSIC_PLAIN_ACTIONS = (
    "music.similar", "music.chart", "music.new_releases", "music.playlist_of_day", "music.queue_show",
    "music.queue_clear", "music.lyrics", "music.unlike", "music.like_album", "music.like_artist",
)
for _aid in MUSIC_PLAIN_ACTIONS:
    MUSIC_COMMANDS[_aid] = AgentCommand(_aid)

# «Поставь трек X в очередь» совпадает с более длинным триггером «поставь трек»:
# хвост фразы важнее глагола запуска.
_TO_QUEUE = re.compile(r"^(.+?)\s+в\s+очередь$", re.IGNORECASE)
_AS_NEXT = re.compile(r"^(.+?)\s+следующим$", re.IGNORECASE)


def _query(ctx) -> str:
    extra = ctx.extra or {}
    return str(ctx.param or extra.get("query") or extra.get("arg") or "").strip()


def _query_handler(action: str):
    def handle(ctx):
        return AgentCommand(action, _query(ctx))
    return handle


for _aid in MUSIC_QUERY_ACTIONS:
    MUSIC_COMMANDS[_aid] = _query_handler(_aid)


def _numeric_handler(action: str):
    """Числа словами превращаются в цифры здесь: клиент получает «2 минуты 40 секунд»."""
    def handle(ctx):
        return AgentCommand(action, digits_in(_query(ctx)))
    return handle


for _aid in ("music.seek_to", "music.volume_set"):
    MUSIC_COMMANDS[_aid] = _numeric_handler(_aid)


def _volume_step_handler(action: str):
    def handle(ctx):
        return AgentCommand(action, volume_step(str((ctx.extra or {}).get("text") or "")))
    return handle


for _aid in ("music.volume_up", "music.volume_down"):
    MUSIC_COMMANDS[_aid] = _volume_step_handler(_aid)


def _play_handler(action: str, prefix: str = ""):
    def handle(ctx):
        query = _query(ctx)
        for pattern, target in ((_TO_QUEUE, "music.queue_add"), (_AS_NEXT, "music.play_next")):
            m = pattern.match(query)
            if m:
                return AgentCommand(target, f"{prefix}{m.group(1)}")
        return AgentCommand(action, query)
    return handle


MUSIC_COMMANDS["music.play_track"] = _play_handler("music.play_track")
MUSIC_COMMANDS["music.play_album"] = _play_handler("music.play_album", "альбом ")
MUSIC_COMMANDS["music.play_playlist"] = _play_handler("music.play_playlist", "плейлист ")
MUSIC_COMMANDS["music.play_artist"] = _play_handler("music.play_artist", "исполнителя ")

register_table(MUSIC_COMMANDS)
