# Генераторы медиа для сайта

Скрипты рисуют диаграммы, графики и видеоролики для `site/media/`.
Запускать из корня репозитория — пути вывода заданы относительно него:

```bash
python site/tools/generate_diagrams_and_charts.py   # PNG: графики и схемы
python site/tools/generate_svg_diagrams.py          # SVG-схемы
python site/tools/generate_all_videos.py            # все ролики (mp4 + webm)
python site/tools/generate_video_hud.py             # по одному ролику
python site/tools/generate_video_noise.py
python site/tools/generate_video_tests.py
```

Нужны Pillow, ffmpeg в PATH и шрифты Windows (Segoe UI, Consolas).
