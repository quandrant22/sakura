"""Все ролики «Сказания о Духе Цветущей Сакуры» (1080p, MP4 H.264 + WebM VP9).

  sakura-legend-five-scrolls      — Пять Свитков: пять гравюр, кандзи кистью, Печати Времени, Река Времени
  sakura-legend-invisible-armor   — Незримый Доспех: снег Хиросигэ, две вести, купол и ворон Кёсая
  sakura-legend-3383-trials       — Три Тысячи Испытаний: ночной Хиросаки, 3 383 бутона и печать 合格

Фоны — настоящие гравюры и фото из кэша fetch_art.py (сначала python -I site/tools/fetch_art.py).

После рендера каждый файл проверяется: ffprobe (кодек, размер, длительность)
и полное декодирование ffmpeg без единой ошибки. Постеры кладутся в
media/images/posters/.

Запуск из корня репозитория:
    python -I site/tools/generate_all_videos.py                # отрендерить и проверить
    python -I site/tools/generate_all_videos.py --verify-only  # только проверить готовые
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # работает и под python -I

import generate_video_armor  # noqa: E402
import generate_video_scrolls  # noqa: E402
import generate_video_trials  # noqa: E402
import legend_common as L  # noqa: E402

MODULES = (generate_video_scrolls, generate_video_armor, generate_video_trials)


def main():
    verify_only = "--verify-only" in sys.argv
    for mod in MODULES:
        if not verify_only:
            mod.main()
        for ext in ("mp4", "webm"):
            print("  [проверка]", L.verify_video(L.VIDEOS_DIR / f"{mod.NAME}.{ext}", mod.SECONDS))
        poster = L.POSTERS_DIR / f"{mod.NAME}.jpg"
        if not poster.exists() or poster.stat().st_size < 10_000:
            raise SystemExit(f"нет постера {poster}")


if __name__ == "__main__":
    main()
