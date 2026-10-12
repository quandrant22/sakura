"""Домен «музыка» (этап 3): 19 действий, все executor=agent.

Бэкенд (SMTC / браузер / приложение) выбирает агент по каноническому id —
на провод уходит только канонический id, без легаси-написаний и без
таблицы перевода в agent/core/agent.py.
"""

from sakura_core.executor import AgentCommand, register_table

# 19 музыкальных действий реестра (music.*, без music_stats.*)
MUSIC_AGENT_ACTIONS = (
    "music.next", "music.prev", "music.restart", "music.play_pause", "music.like",
    "music.dislike", "music.now_playing", "music.history",
    "music.liked_tracks", "music.playlists", "music.shuffle", "music.repeat",
    "music.seek_forward", "music.seek_back", "music.podcasts", "music.mute",
    "music.volume_up", "music.volume_down", "music.wave",
)

# Явная таблица: канонический id → команда агенту.
MUSIC_COMMANDS = {aid: AgentCommand(aid) for aid in MUSIC_AGENT_ACTIONS}
# Алиасы реестра (другой context) — тот же id на проводе.
MUSIC_COMMANDS["music.restart_playing"] = AgentCommand("music.restart")

register_table(MUSIC_COMMANDS)
