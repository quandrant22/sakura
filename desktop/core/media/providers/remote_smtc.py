"""remote_smtc — внешний музыкальный плеер (прежнее поведение агента).

Код перенесён в desktop/core/music.py (SMTC, API Яндекс.Музыки), yamusic_app.py
(приложение Яндекс.Музыки) и music_listener.py (системный звук для эквалайзера);
здесь — единый вход для MediaService и карточки «играет внешнее приложение».
"""
import asyncio

from desktop.core import music, yamusic_app


async def now_playing() -> dict | None:
    """Что играет во внешнем приложении (SMTC) — для карточки «Сейчас играет»."""
    try:
        info = await asyncio.wait_for(music._smtc_get_info(), timeout=3.0)
    except Exception:
        return None
    if not info or not info.get("title"):
        return None
    return {"source": "external", "title": info.get("title", ""), "artist": info.get("artist", ""),
            "album": info.get("album", ""), "status": info.get("status", "")}


async def control(cmd: str) -> bool:
    """play_pause | next | prev через SMTC."""
    return bool(await music._smtc_control(cmd))


def open_wave() -> bool:
    return bool(yamusic_app.open_wave())
