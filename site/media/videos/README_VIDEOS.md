# 🎬 Медиатека видеороликов Sakura AI (`site/media/videos/`)

В эту папку помещаются демонстрационные видеоролики, сквозные записи экрана и видео-презентации работы голосового ассистента **Sakura AI**.

## 📌 Встроенные демонстрационные видеоролики
Сайт автоматически подключен к следующим предустановленным видео высокого разрешения (1080p Full HD):
1. `sakura-hud-voice-core.mp4` / `sakura-hud-voice-core.webm` — Реактивный HUD Сакуры, нейро-ядро, свечение состояний (`LISTENING`, `THINKING`, `SPEAKING`, `IDLE`), звуковая волна и лепестки сакуры.
2. `sakura-noise-handshake.mp4` / `sakura-noise-handshake.webm` — Криптографическое рукопожатие `Noise_IK_25519_ChaChaPoly_BLAKE2s`, передача кадров «SK», защита от replay-атак и вердикт ProVerif.
3. `sakura-test-suite-3297.mp4` / `sakura-test-suite-3297.webm` — Демонстрация непрерывного прогона 3297+ тестов без регрессий в терминале.

---

## 🚀 Как добавить свои записи экрана
Чтобы добавить свои реальные скринкасты работы Сакуры:
1. Запишите экран (например, через OBS Studio, GeForce Experience или Windows Game Bar `Win + G`).
2. Сохраните файл в формате `.mp4` (кодек H.264 или H.265) или `.webm` (кодек VP9/AV1).
3. Скопируйте видеофайл прямо в эту директорию (`site/media/videos/`).

### Рекомендуемые имена файлов для витрины:
- `user-demo-voice.mp4` — Голосовое управление музыкой и ПК.
- `user-demo-gamesense.mp4` — Работа оверлея GameSense и Screen Ink в играх (Dota 2, CS2, Cyberpunk).
- `user-demo-browser.mp4` — Автономный агент форм на базе Gemma 4.
- `user-demo-discord.mp4` — Работа в голосовом канале Discord (Call Mode + распознавание друзей).

### Рекомендуемые параметры кодирования для веб-видео:
```bash
# Оптимальный битрейт для быстрого старта в веб-плеере (с поддержкой Range 206 в Nginx):
ffmpeg -i your_raw_recording.mp4 -c:v libx264 -preset fast -crf 20 -movflags +faststart -c:a aac -b:a 192k site/media/videos/user-demo-voice.mp4
```
Флаг `-movflags +faststart` перемещает метаданные `moov atom` в начало файла, что позволяет браузеру начать мгновенное воспроизведение без ожидания полной загрузки файла!
