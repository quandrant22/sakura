"""Тоны озвучки: русские id TTS (modules/tts_server.TONES) ↔ id протокола v2."""

TONE_IDS = {"нейтрально": "neutral", "тепло": "warm", "сухо-иронично": "dry",
            "серьёзно": "serious", "тихо": "quiet", "бодро": "cheerful",
            "томно": "sultry"}
TONE_FROM_ID = {v: k for k, v in TONE_IDS.items()}
