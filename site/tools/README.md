# Генераторы «Сказания о Духе Цветущей Сакуры»

Скрипты рисуют ролики, иллюстрации и шрифт для `site/`. Запускать из корня
репозитория — пути вывода считаются от него.

```bash
python site/tools/generate_all_videos.py            # 3 ролика 1080p (MP4 H.264 + WebM VP9) + постеры, затем проверка
python site/tools/generate_all_videos.py --verify-only   # только проверить готовые ролики
python site/tools/generate_video_scrolls.py         # по одному: «Пять Свитков»
python site/tools/generate_video_armor.py           #            «Незримый Доспех»
python site/tools/generate_video_trials.py          #            «Три Тысячи Испытаний»
python site/tools/generate_diagrams_and_charts.py   # 6 иллюстраций тушью (PNG): Река Времени и свитки I–V
python site/tools/generate_svg_diagrams.py          # 2 векторных свитка (SVG)
python site/tools/build_font_subset.py              # подмножество шрифта под текст index.html и app.js
```

| Файл | Что внутри |
| --- | --- |
| `legend_common.py` | палитра, поиск шрифтов, проверка глифов, небо, ветви, лепестки, сфера духа, печати, свиток, кодирование и проверка видео, данные пяти свитков |
| `generate_video_*.py` | сцены роликов; у каждого `NAME`, `SECONDS`, `build()` и `main()` |
| `generate_diagrams_and_charts.py` | Река Времени (коммиты по месяцам из `git log`), Свиток Умений (из `sakura_core/capabilities.yaml`) и иллюстрации свитков |
| `build_font_subset.py` | `styles/fonts/legend-serif-{regular,bold}.woff` из Noto Serif CJK JP + лицензия OFL |

## Что нужно

- Python 3.11+ с Pillow, numpy, fontTools и PyYAML (всё есть в `venv` сервера);
- `ffmpeg` и `ffprobe` в PATH (кодеки libx264 и libvpx-vp9);
- шрифты с кириллицей и кандзи. На Linux: `apt install fonts-noto-cjk` — их
  находит `fc-match`. На Windows подойдут Yu Mincho и Yu Gothic.

Перед каждой надписью проверяется, что в шрифте есть все её глифы. Если
символа нет, генератор падает с ошибкой — квадратиков в кадре не бывает.

Рендер тяжёлый: на сервере запускайте с `nice -n 19`, чтобы не мешать
Сакуре. Ролики собираются примерно за 5–8 минут.

## После генерации

1. После правки текста страницы пересоберите шрифт: `build_font_subset.py`.
2. `*.png` и `*.jpg` стоят в корневом `.gitignore`, поэтому картинки сайта
   добавляются принудительно: `git add -f site/media/images`.
3. На сервере опубликуйте витрину: `/usr/local/bin/sakura-site-sync`
   (каталог `tools/` не публикуется).
