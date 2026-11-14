# Видения «Сказания о Духе Цветущей Сакуры»

Три ролика 1080p, каждый в двух форматах: MP4 (H.264, `+faststart`) и WebM (VP9).
Постеры лежат в `../images/posters/`.

| Файл | Длительность | О чём |
| --- | --- | --- |
| `sakura-legend-five-scrolls` | 29 с | Пролог 桜の伝説, пять свитков с Печатями Времени, эпилог |
| `sakura-legend-invisible-armor` | 21 с | Две вести рукопожатия Noise IK, шестигранный купол, отвергнутый ворон |
| `sakura-legend-3383-trials` | 20 с | 3 383 бутона-испытания, пять вех пути и печать 合格 |

Ролики рисует `site/tools/generate_all_videos.py` — он же проверяет каждый
файл: ffprobe и полное декодирование без ошибок.

## Свой ролик

Положите файл в эту папку и закодируйте его так, чтобы браузер начал
показ сразу и мог перематывать (nginx отдаёт `206 Partial Content`):

```bash
ffmpeg -i запись.mp4 -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart \
       -c:a aac -b:a 160k site/media/videos/имя.mp4
ffmpeg -i запись.mp4 -c:v libvpx-vp9 -b:v 0 -crf 32 -row-mt 1 -c:a libopus site/media/videos/имя.webm
```
