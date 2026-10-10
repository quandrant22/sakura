# Сборка агента Сакуры в .exe

## Быстро

```batch
cd agent
build.bat
```

Результат: `dist\Sakura\Sakura.exe`

## Что нужно

- Windows 10/11
- Python 3.11 и окружение из `requirements.lock.txt`
  (см. [README_INSTALL.md](README_INSTALL.md))
- ~6 ГБ свободного места (torch CPU, GigaAM, Vosk small)

## Установка зависимостей

```batch
venv\Scripts\python.exe -m pip install -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python.exe -m pip install pyinstaller
```

## Что внутри сборки

- распознавание — GigaAM (`v3_e2e_ctc`, запасной `v2_ctc`), модель
  скачивается при первом запуске;
- `vosk-model-small-ru-0.22` — только для слова «Сакура»;
- `extension/` — расширение браузера.

Whisper и Yandex SpeechKit не используются (строки `whisper` в
`build.bat` — наследие, на работу не влияют).

## Структура после сборки

```
dist/Sakura/
├── Sakura.exe          ← запускать
├── extension/          ← расширение браузера
├── vosk-model-small-ru-0.22/  ← модель слова «Сакура»
├── _internal/          ← библиотеки (не трогать)
└── ...
```

## Настройка

Рядом с `Sakura.exe` положи `.env` (образец — `.env.example`):
`DEVICE_ID`, `WS_TOKEN`, `VPS_WS_URL` и др. Токен в сборку не зашит.

## Установка расширения

1. Открой страницу расширений браузера (Chrome/Edge/Opera/Brave),
   включи «Режим разработчика».
2. «Загрузить распакованное» → `dist\Sakura\extension\`.
3. ID расширения впиши в `.env` как `SAKURA_EXTENSION_ID`.

## Автозапуск

1. Win+R → `shell:startup`
2. Создай ярлык на `Sakura.exe` (или на `start_sakura.bat` при запуске из исходников)
