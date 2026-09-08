#!/usr/bin/env python3
"""
tools/voice_test.py — прослушивание голосов Live API для Сакуры.

Синтезирует одну и ту же фразу каждым голосом из списка и сохраняет в
voice_samples/<voice_name>.wav (24 кГц, 16 бит, моно — как отдаёт Live API),
чтобы Мастер сравнил кандидатов и выбрал голос.

Использование:
  python3 tools/voice_test.py                     # женские кандидаты (10 шт, по умолчанию)
  python3 tools/voice_test.py --all               # все 30 голосов
  python3 tools/voice_test.py --voices Kore,Leda  # конкретные
  python3 tools/voice_test.py --text "своя фраза"

Голос меняется без правки кода: строка TTS_VOICE в .env + рестарт
(systemctl restart sakura). Полный список голосов — в .env.example.
"""

import argparse
import asyncio
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import tts_server  # noqa: E402  — переиспользуем боевой синтез

# ── Все 30 предустановленных голосов Live API ────────────────────────
VOICES: dict[str, str] = {
    "Zephyr":         "Bright",
    "Puck":           "Upbeat",
    "Charon":         "Informative",
    "Kore":           "Firm",
    "Fenrir":         "Excitable",
    "Leda":           "Youthful",
    "Orus":           "Firm",
    "Aoede":          "Breezy",
    "Callirrhoe":     "Easy-going",
    "Autonoe":        "Bright",
    "Enceladus":      "Breathy",
    "Iapetus":        "Clear",
    "Umbriel":        "Easy-going",
    "Algieba":        "Smooth",
    "Despina":        "Smooth",
    "Erinome":        "Clear",
    "Algenib":        "Gravelly",
    "Rasalgethi":     "Informative",
    "Laomedeia":      "Upbeat",
    "Achernar":       "Soft",
    "Alnilam":        "Firm",
    "Schedar":        "Even",
    "Gacrux":         "Mature",
    "Pulcherrima":    "Forward",
    "Achird":         "Friendly",
    "Zubenelgenubi":  "Casual",
    "Vindemiatrix":   "Gentle",
    "Sadachbia":      "Lively",
    "Sadaltager":     "Knowledgeable",
    "Sulafat":        "Warm",
}

# Женские/нейтральные кандидаты под сдержанную дворецкую (первое прослушивание).
# Aoede — текущий голос, для сравнения.
DEFAULT_CANDIDATES = [
    "Aoede",         # Breezy    — текущий, для сравнения
    "Kore",          # Firm      — твёрдый, деловой — под дворецкую
    "Erinome",       # Clear     — чёткий, без лишней эмоции
    "Schedar",       # Even      — ровный, невозмутимый
    "Vindemiatrix",  # Gentle    — мягкий, но не приторный
    "Gacrux",        # Mature    — взрослый, не девчачий
    "Achernar",      # Soft      — тихий, деликатный
    "Sulafat",       # Warm      — тёплый, если захочется человечнее
    "Leda",          # Youthful  — молодой, для контраста
    "Alnilam",       # Firm      — второй «твёрдый» вариант
]

# Тестовая фраза — в дворецком регистре: числа, названия, обращение —
# то, что Сакура произносит каждый день.
DEFAULT_TEXT = (
    "Palworld запущен, Мастер. Загрузка процессора девяносто восемь "
    "процентов — полагаю, вы в курсе. Последнее достижение выбито "
    "вчера в двадцать два сорок четыре."
)

DEFAULT_DELAY = 3.0  # сек между голосами — не упереться в лимиты Live API


async def synth_one(voice: str, text: str, outdir: str) -> float:
    """Синтез одним голосом → WAV. Возвращает длительность (сек) или -1."""
    t0 = time.monotonic()
    packets = await tts_server._synthesize(text, voice=voice)
    if not packets:
        return -1.0

    path = os.path.join(outdir, f"{voice}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)                            # моно
        w.setsampwidth(2)                            # 16 бит
        w.setframerate(tts_server.TTS_SAMPLE_RATE)   # 24000 Гц
        frames = b"".join(packets)
        w.writeframes(frames)

    duration = len(frames) / (2 * tts_server.TTS_SAMPLE_RATE)
    print(f"  {voice:<15} OK  {duration:5.1f}с  {len(packets):3d} пакетов "
          f"({time.monotonic()-t0:.1f}с синтеза) → {path}")
    return duration


async def main_async(args, voices: list[str], outdir: str) -> int:
    ok, fail = [], []
    for i, voice in enumerate(voices):
        print(f"[{i+1}/{len(voices)}] {voice} ({VOICES.get(voice, '?')})…")
        try:
            dur = await synth_one(voice, args.text, outdir)
        except Exception as e:
            print(f"  {voice:<15} ОШИБКА: {e}")
            dur = -1.0
        (ok if dur >= 0 else fail).append(voice)
        if dur < 0:
            print(f"  {voice:<15} синтез не удался (нет ключа/ошибка API)")
        if i < len(voices) - 1:
            await asyncio.sleep(args.delay)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Синтез тестовой фразы голосами Live API → voice_samples/*.wav")
    parser.add_argument("--all", action="store_true",
                        help="все 30 голосов вместо женских кандидатов")
    parser.add_argument("--voices", default="",
                        help="список через запятую, например: Kore,Leda")
    parser.add_argument("--text", default=DEFAULT_TEXT,
                        help="фраза для синтеза (по умолчанию — дворецкий регистр)")
    parser.add_argument("--out", default="voice_samples",
                        help="каталог для WAV (по умолчанию voice_samples/)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"пауза между голосами, сек (по умолчанию {DEFAULT_DELAY})")
    args = parser.parse_args()

    if args.voices:
        voices = [v.strip() for v in args.voices.split(",") if v.strip()]
        unknown = [v for v in voices if v not in VOICES]
        if unknown:
            parser.error(f"неизвестные голоса: {', '.join(unknown)}")
    elif args.all:
        voices = list(VOICES)
    else:
        voices = list(DEFAULT_CANDIDATES)

    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
    os.makedirs(outdir, exist_ok=True)

    label = ("все голоса" if args.all
             else args.voices if args.voices
             else "женские кандидаты")
    print(f"Голосов: {len(voices)} ({label})")
    print(f"Фраза:   {args.text!r}")
    print(f"Каталог: {outdir}\n")

    rc = asyncio.run(main_async(args, voices, outdir))

    # Итоговая сводка: файл + характеристика голоса
    print("\n" + "═" * 64)
    print("РЕЗУЛЬТАТ — сравните файлы в плеере:")
    print("═" * 64)
    for voice in voices:
        path = os.path.join(outdir, f"{voice}.wav")
        mark = "→ " + path if os.path.exists(path) else "× файл не создан"
        print(f"  {voice:<15} {VOICES.get(voice, '?'):<14} {mark}")
    print("\nСмена голоса: строка TTS_VOICE в .env + systemctl restart sakura")
    return rc


if __name__ == "__main__":
    sys.exit(main())

