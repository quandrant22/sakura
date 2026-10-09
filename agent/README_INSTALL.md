# Установка агента Сакуры (Windows)

## 1. Что нужно

- Windows 10/11, микрофон, ~6 ГБ свободного места
- Git: `winget install --id Git.Git -e`
- Python **3.11** (набор пакетов проверен под него):
  `winget install --id Python.Python.3.11 -e`

## 2. Код и окружение

```bat
git clone https://github.com/quandrant22/sakura.git C:\sakura-git
cd C:\sakura-git\agent
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
venv\Scripts\python.exe -m pip check
```

Установка идёт до 20 минут (torch CPU). Git должен быть в PATH:
GigaAM ставится из git-репозитория.

## 3. Модель слова «Сакура» (Vosk)

Скачай https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
и распакуй в `agent\`, чтобы получилась папка
`agent\vosk-model-small-ru-0.22`. Модель GigaAM скачается сама при
первом запуске.

## 4. Настройка .env

```bat
copy .env.example .env
notepad .env
```

Обязательно: `DEVICE_ID` (имя устройства, добавленное на сервере) и
`WS_TOKEN`. Остальные переменные описаны в [README.md](README.md) и
`.env.example`. Файл `.env` не коммитится.

## 5. Запуск

```bat
start_sakura.bat
```

Лог: `agent\logs\sakura.log`.

## 6. Расширение браузера (Chrome, Edge, Opera, Brave)

1. Открой страницу расширений (`chrome://extensions`, `edge://extensions`,
   `opera://extensions`) и включи режим разработчика.
2. «Загрузить распакованное» → папка `agent\extension`.
3. Скопируй ID расширения и впиши в `.env`: `SAKURA_EXTENSION_ID=<ID>`,
   перезапусти агента. В логе: `[extension] Готово, версия …`.

Firefox не поддерживается.

## Типичные проблемы

| Симптом | Что делать |
|---|---|
| В оверлее «Не задан WS_TOKEN (.env)» | впиши `WS_TOKEN=` в `agent\.env` и перезапусти |
| В логе код 4401 / отказ по устройству | `DEVICE_ID` не добавлен на сервере или неверный токен |
| «No input device available», Сакура не слышит | проверь микрофон в «Параметры → Конфиденциальность → Микрофон» и устройство ввода по умолчанию |
| «Cannot find command 'git'» при pip install | установи Git и открой новое окно консоли |
| Расширение не подключается | проверь `SAKURA_EXTENSION_ID` и что порты `EXTENSION_PORTS` не заняты |
