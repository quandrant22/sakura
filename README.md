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

### 4. Применить патчи в main.py

**Импорты** (добавить после существующих):
```python
from modules.ws_auth import check_token, is_master_device, reject, validate_secret_on_startup
from modules.rituals import should_greet_device, get_greeting_prompt, should_farewell, get_farewell_prompt, mark_master_interaction, get_return_context
from modules.mood_vector import get_mood_context as get_mood_vector_context, auto_detect_from_llm, mark_interaction as mood_mark_interaction
from modules.mood_broadcast import broadcast_mood_after_reply
from memory.db import ensure_ready, add_to_self, get_self_context
```

**В async def main()** — первые строки:
```python
validate_secret_on_startup()
await asyncio.to_thread(ensure_ready)
```

**ws_handler** — заменить целиком на `ws_handler_secure.py`

**В handle_message** (блок Мастера, после update_master_status):
```python
mark_master_interaction()   # rituals.py
mood_mark_interaction()     # mood_vector.py
```

**В ask_gemini()** — после auto_detect_mood_from_reply:
```python
asyncio.create_task(broadcast_mood_after_reply(reply, user_message, "neutral", connected_devices))
```

**В ask_gemini_voice()** — после определения emotion:
```python
asyncio.create_task(broadcast_mood_after_reply(clean_text, user_message, emotion, connected_devices))
```

**В personality.py** — добавить вызовы из personality_patch.py:
```python
from personality_patch import get_self_block, get_return_hint, get_adaptation_context
```

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
| `ws_handler_secure.py` | Защищённый ws_handler (замена) |
| `memory/db.py` | SQLite-память + самопамять Сакуры |
| `modules/rituals.py` | Ритуалы: приветствие, прощание, возвращение |
| `modules/reflection.py` | Рефлексия с самопамятью |
| `modules/mood_vector.py` | Настроение как вектор valence/arousal |
| `modules/mood_broadcast.py` | Рассылка состояния орба устройствам |
| `personality_patch.py` | Патч personality.py: самопамять в промпт |
| `main_patch_phase1.py` | Инструкции патча main.py |
| `tests/` | 59 тестов критического пути |

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
| `modules/proactive_patch.py` | — | Инструкции интеграции в proactive_loop и ws_handler |

### Применить патчи

Открой `modules/proactive_patch.py` — там три блока с комментариями:
1. В `proactive_loop()` — тихий режим + инсайты
2. В `ws_handler`, блок `register` — утренний брифинг
3. В `ws_handler`, блок `ping` — обновление наблюдателя окна
4. В `handle_message` — проверка цепочек до ask_gemini

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
