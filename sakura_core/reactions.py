"""Shared reaction logic — mood check + sticker/GIF selection.

Adapters handle I/O (send sticker/GIF to the right chat).
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("sakura.reactions")


def get_mood_reaction(text: str) -> Optional[dict]:
    """Check if text warrants a mood reaction.

    Returns {"emotion": str, "valence": float, "arousal": float} or None.
    """
    try:
        from modules.mood_vector import get_current
        from modules.reactions import should_react, detect_reaction

        mood = get_current()
        v = mood.get("valence", 0.0)
        a = mood.get("arousal", 0.3)
        if should_react(text, v, a):
            reaction = detect_reaction(text, v, a)
            if reaction:
                return {"emotion": reaction["emotion"], "valence": v, "arousal": a}
    except Exception as e:
        log.debug(f"[reactions] mood check: {type(e).__name__}: {e}")
    return None


def get_sticker_or_gif(emotion: str) -> tuple[Optional[str], Optional[str]]:
    """Get a sticker (preferred) or GIF for the given emotion.

    Returns (sticker_url_or_None, gif_url_or_None).
    """
    sticker = None
    try:
        from modules.reactions import get_random_sticker
        sticker = get_random_sticker(emotion)
    except Exception as e:
        log.debug(f"[reactions] sticker: {type(e).__name__}: {e}")

    gif = None
    if not sticker:
        try:
            from modules.reactions import get_random_gif
            gif = get_random_gif(emotion)
        except Exception as e:
            log.debug(f"[reactions] gif: {type(e).__name__}: {e}")

    return sticker, gif
