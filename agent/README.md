# Сакура — агент для ПК

Агент работает на компьютере и связан с сервером Сакуры по WebSocket:
слышит слово «Сакура», распознаёт фразу, отправляет её на сервер,
озвучивает ответ и выполняет команды (громкость, приложения, музыка,
браузер через расширение). Интерфейс — оверлей PyQt6 со сферой.

Установка по шагам — [README_INSTALL.md](README_INSTALL.md),
сборка .exe — [BUILD.md](BUILD.md).

## Распознавание речи

| Задача | Чем |
|---|---|
| Слово «Сакура» | Vosk `vosk-model-small-ru-0.22` (только wake word) |
| Начало/конец фразы | Silero VAD |
| Текст фразы | GigaAM `v3_e2e_ctc` (запасная модель — `v2_ctc`), на CPU |

Whisper и Yandex SpeechKit для распознавания и озвучки не используются.
Озвучку присылает сервер (PCM 24 кГц), агент только проигрывает её.

## Быстрый старт

```bat
cd agent
copy .env.example .env
notepad .env          & rem DEVICE_ID и WS_TOKEN обязательны
start_sakura.bat
```

Без `WS_TOKEN` агент не подключается к серверу и пишет в оверлее
«Не задан WS_TOKEN (.env)».

## Переменные .env

| Переменная | Назначение |
|---|---|
| `DEVICE_ID` | имя устройства; должно быть в списке устройств на сервере |
| `WS_TOKEN` | токен сервера (секрет, вписывается вручную) |
| `VPS_WS_URL` | адрес сервера, `ws://host:8765` или `wss://…` |
| `STT_ENGINE` | `gigaam` (по умолчанию) или `vosk` |
| `GIGAAM_MODEL` | `v3_e2e_ctc` (рекомендуется) или `v2_ctc` |
| `GIGAAM_DEVICE` | только `cpu` |
| `SAKURA_EXTENSION_ID` | ID расширения браузера; пусто — любое расширение |
| `EXTENSION_PORTS` | порты локального сервера расширения, `8766,8767,8768,8769` |
| `VOLUME_STEP` | шаг «громче/тише» для музыки без числа, % (10) |
| `VAD_END_SILENCE` | тишина до конца фразы, сек (в `config.py`, 1.0) |
| `VAD_END_SILENCE_SHORT` | то же для короткой фразы, сек (0.7) |
| `VAD_SHORT_UTTER_SEC` | фраза короче этого — «короткая», сек (1.5) |
| `PLAYER_PREROLL_MS` | предзаполнение плеера озвучки, мс (0 — выключено) |
| `YANDEX_MUSIC_TOKEN` | токен Яндекс Музыки (по желанию) |

`YANDEX_API_KEY`, `YANDEX_FOLDER_ID` — остатки SpeechKit, не используются.

## Логи

`agent\logs\sakura.log`. При старте ожидаются строки
`Loaded … built-in commands`, `[STT] Движок: GigaAM v3_e2e_ctc (cpu)`,
`Подключено к VPS`.

## Тесты

```bat
cd agent
venv\Scripts\python.exe -m pytest tests -q
```
