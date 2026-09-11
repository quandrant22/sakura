# Sakura VPS — Обновление (Фазы 0-2)

## Быстрый старт

### 1. Перевыпусти скомпрометированные ключи
```
Gemini: https://aistudio.google.com/ → API Keys → Delete + Create
OAuth:  https://console.cloud.google.com/apis/credentials
```

### 2. Создай .env
```bash
cp .env.example .env
python generate_token.py  # скопируй WS_SECRET в .env
nano .env                 # заполни TELEGRAM_TOKEN, MASTER_ID, GEMINI_KEY_*
```

### 3. Установи зависимость
```bash
pip install sqlite-vec
```

### 4. Патчи уже применены

Патчи из `docs/legacy/` (ws_handler, personality, proactive, main phase1) уже вкачены в `main.py` и `modules/ws_handlers.py`. Инструкции сохранены в `docs/legacy/` для истории, повторно применять не нужно.

### 5. Прогони тесты
```bash
python -m pytest tests/ -v
# Ожидается: 59 passed
```

---

## Файлы этого обновления

| Файл | Описание |
|------|----------|
| `modules/ws_auth.py` | Аутентификация WS по токену |
| `memory/db.py` | SQLite-память + самопамять Сакуры |
| `modules/rituals.py` | Ритуалы: приветствие, прощание, возвращение |
| `modules/reflection.py` | Рефлексия с самопамятью |
| `modules/mood_vector.py` | Настроение как вектор valence/arousal |
| `modules/mood_broadcast.py` | Рассылка состояния орба устройствам |
| `tests/` | Тесты критического пути |

> Исторические патч-инструкции (`ws_handler_secure`, `personality_patch`, `proactive_patch`, `main_patch_phase1`) сохранены в `docs/legacy/` — уже вкачены в `main.py` и `modules/ws_handlers.py`.

---

## По поводу TLS (без домена)

Пока оставляем `ws://` с токеном — это достаточно для личного использования.
Когда появится домен (или Cloudflare Tunnel):
- Установи Caddy, скопируй `Caddyfile.example`
- Замени `"0.0.0.0"` на `"127.0.0.1"` в `websockets.serve()`
- Обнови `VPS_WS_URL` в `.env` на агенте на `wss://`

---

## Фаза 3 — Автономность и присутствие

### Новые файлы

| Файл | Бэклог | Описание |
|------|--------|----------|
| `modules/briefing.py` | №17 | Утренний брифинг при подключении устройства |
| `modules/window_watcher.py` | №16, №22 | Наблюдатель окна + авто-тишина на созвонах |
| `modules/chains.py` | №18, №19 | Цепочки действий + градиент автономии |
| `modules/proactive_patch.py` | — | Инструкции интеграции в proactive_loop и ws_handler (см. `docs/legacy/`, уже вкачены) |

### Патчи уже применены

Исторические инструкции сохранены в `docs/legacy/` — тихий режим, инсайты, брифинг и цепочки уже вкачены в `main.py` и `modules/ws_handlers.py`, повторно применять не нужно.

### Встроенные цепочки

| Фраза Мастера | Что делает |
|---|---|
| «подготовь к стриму» | OBS + своя волна + громкость 40% |
| «рабочий режим» | VS Code + браузер + громкость 25% |
| «ночной режим» | громкость 15% + тихая музыка + «спокойной ночи» |
| «тишина» / «созвон» | выключить звук + пауза |

### Авто-тишина

Sakura автоматически замолкает когда:
- Детектирует Teams/Zoom/Discord в активном окне
- Обнаруживает полноэкранный режим игры

Тишина снимается автоматически через 2 часа (созвон) или 30 минут (игра).
