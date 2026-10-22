# Sakura desktop — архитектура

Новый настольный клиент Сакуры. Заменит `agent/` на всех устройствах владельца
(сейчас Windows, позже Linux и macOS). Пока новая версия не прошла проверку
полноты ([PARITY.md](PARITY.md)), `agent/` остаётся рабочим и не удаляется.

## Части

```
VPS (сервер Сакуры)
   ▲  WebSocket, прежний протокол + proto: 2 (PROTOCOL.md, «Сервер ↔ ядро»)
   │
desktop/core  ── Python-сервис без окна
   │   голос (Vosk wake-word, GigaAM STT, плеер), команды, расширение браузера,
   │   присутствие, приложения/файлы, музыка, чайник, Outbox, логи
   │   core/platform/  — всё, что зависит от ОС (единственное место для WinAPI)
   │   core/api/       — локальный API для интерфейса
   ▼  WebSocket 127.0.0.1:<порт> + токен + Origin (PROTOCOL.md, «Ядро ↔ интерфейс»)
desktop/ui       Electron + React + TypeScript + Tailwind (Vite), Zustand
desktop/overlay  адаптер старого PyQt6-оверлея к тому же локальному API
```

| Папка | Что внутри |
|---|---|
| `core/` | порт `agent/core/*` с сохранением поведения |
| `core/platform/` | `base.py` — интерфейс `Platform`; `windows.py` — реализация; `linux.py`, `macos.py` — заглушки (`NotImplementedError`) |
| `core/api/` | локальный WebSocket-сервер для интерфейса и оверлея |
| `ui/` | Electron main/preload (`ui/electron`), React-приложение (`ui/src`) |
| `overlay/` | адаптер PyQt6-оверлея (`agent/ui/overlay.py`) — вид не меняется |
| `tools/mock_server.py` | мок сервера (протокол v2) на фикстурах `tools/fixtures/*.json` |
| `docs/` | этот файл, PROTOCOL.md, PARITY.md, UI.md |
| `tests/` | pytest ядра и инструментов |

## Правила

1. Ядро и интерфейс общаются **только** через локальный API (JSON-события и
   команды). Интерфейс не знает про WinAPI, микрофон и расширение браузера.
2. Вызовы ОС (громкость, окна, горячие клавиши, простой пользователя,
   автозапуск, захват системного звука, питание) — только в `core/platform`.
   Тест `tests/test_platform.py::test_no_windll_outside_platform` ловит
   `windll`/`winreg` вне этого пакета.
3. Клиент сервера — прежний WebSocket-клиент (`protocol.py`, `Outbox`) плюс
   поле `proto: 2` в регистрации. Если сервер не поддерживает v2
   (`registered.proto < 2` или `error.code = unsupported`), экраны,
   которым нужны новые данные, показывают «сервер не поддерживает» без ошибок.
4. Секреты (`WS_TOKEN`, `YANDEX_MUSIC_TOKEN` и т.п.) — только в `.env`;
   в коде и логах их нет. Токен локального API лежит в
   `%LOCALAPPDATA%\Sakura\ui.token` с правами только текущего пользователя.

## Безопасность интерфейса

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`;
  в окно попадает только узкий preload-мост `window.sakura`.
- CSP без внешних ресурсов: `default-src 'self'`; `connect-src` — только
  `ws://127.0.0.1:*` (локальный API). Ослабление CSP есть только в `vite serve`.
- Навигация и новые окна запрещены; внешние http(s)-ссылки открываются в браузере.
- Одно приложение на пользователя (`requestSingleInstanceLock`).

## Запуск (разработка)

```powershell
# ядро
C:\sakura-git\agent\venv\Scripts\python.exe -m desktop.core --headless
# мок-сервер
C:\sakura-git\agent\venv\Scripts\python.exe -m desktop.tools.mock_server --port 8765
# интерфейс
cd desktop\ui; npm install; npm run dev      # или npm run build; npm start
# тесты
python -m pytest -c desktop\pytest.ini --rootdir desktop desktop\tests -q
cd desktop\ui; npm test; npm run lint
```

## Фазы

0 — основа (каркас, документы, мок-сервер); 1 — ядро; 2 — Главная;
3 — Устройства, Настройки, Профиль; 4 — Сценарии; 5 — Память и Профиль;
6 — полировка; 7 — переключение (только с разрешения владельца).
