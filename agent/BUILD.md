# Сборка агента Сакуры в .exe

## Быстро

```batch
cd agent
build.bat
```

Результат: `dist\Sakura\Sakura.exe`

## Что нужно

- Windows 10/11
- Python 3.12+
- ~2GB свободного места (torch + whisper модели)

## Установка зависимостей

```batch
pip install -r requirements.txt
pip install pyinstaller
```

## Ручная сборка

```batch
pyinstaller --name "Sakura" --onedir --windowed --noconfirm ^
    --add-data "extension;extension" ^
    --add-data "vosk-model-small-ru-0.22;vosk-model-small-ru-0.22" ^
    --hidden-import torch --hidden-import whisper --hidden-import vosk ^
    --collect-all whisper --collect-all vosk --collect-all silero_vad ^
    sakura.py
```

## Структура после сборки

```
dist/Sakura/
├── Sakura.exe          ← запускать
├── extension/          ← расширение браузера
├── vosk-model-small-ru-0.22/  ← модель распознавания
├── _internal/          ← библиотеки (не трогать)
└── ...
```

## Настройка

Все настройки уже внутри `config.py` — `.env` не нужен.
Для смены устройства: отредактируй `DEVICE_ID` в `config.py` перед сборкой.

## Установка расширения

1. Открой Opera GX → `opera://extensions`
2. Включи «Режим разработчика»
3. Нажми «Загрузить распакованное расширение»
4. Выбери папку `dist\Sakura\extension\`

## Размер

~1.5-2GB (включая torch, whisper, vosk модели)

## Автозапуск

Чтобы Сакура запускалась при старте Windows:
1. Win+R → `shell:startup`
2. Создай ярлык на `Sakura.exe`
