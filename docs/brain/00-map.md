# 00. Карта «мозгов» Сакуры (серверная часть)

Срез: master `6f0fb74`, журнал за 25.09–09.10 (15 суток), БД `memory/sakura.db`
(read-only, агрегаты). Только серверная часть; агент на ПК — отдельно.

## 1. Потоки «вход → ответ»

### Голос (ПК/телефон → WebSocket)

```
агент: voice_command ─► adapters/ws.py ws_handler (обработчики сокета вызываются ПОСЛЕДОВАТЕЛЬНО)
  └► handle_voice_command (finally: ensure_turn_end → tts_end, если ход не закрыт фразой ack)
      ├─ стоп/отмена/pending/подтверждения (sakura_core/pending_dialog, bridge.handle_v3_confirm)
      ├─ предконнект Live-сессии TTS (modules/tts_server.preconnect)
      ├─ v3_fast_path (sakura_core/bridge.py)
      │    Router.route: реестр (точное/нечёткое) → LLM-классификатор (цепочка chat, gemma)
      │    ∥ параллельно prefetch: ask_gemini_voice + VoiceGate (ждёт вердикт, таймаут 4с)
      │    вердикт «команда» → on_command снимает prefetch → execute_decision
      │       vps-действие → текст → озвучка; агентная → cmd_id → acks.arm (ack по command_result)
      ├─ голосовые триггеры, цепочки, «отправь в телеграм» и прочие ветки-команды
      └─ «не команда» → VoiceGate.open → adapters/voice.stream_llm_to_tts
           _build_system(query) + история(VOICE_HISTORY_LIMIT) → stream_tokens (цепочка voice)
           → предложения → стадии TTS (короткий ответ — одна сессия) → tts_chunk… → tts_end
```

### Telegram (мастер)

```
aiogram → adapters/telegram.handle_message → (команды /…, медиа adapters/media)
  └► v3_fast_path(ack=Telegram) | ask_gemini(текст)
       _build_system("") (кэш) + история до 60 → generate (цепочка chat)
       после ответа (save_history=True) в фоне: extract_and_remember (LLM), summarize_session (LLM,
       по порогу), timeline, mood, self_correction, secret_diary.write_entry (LLM)
```

Гости и группы — `adapters/group_chat.py` (персона «не Мастер», цепочка background).

### Проактивные сообщения

```
sakura_core/proactive.proactive_loop (каждые 90–210 с; тишина 23:00–07:00):
  задачи (due/upcoming) → календарь → «факт» (modules/proactive.get_fact_trigger, без LLM)
  → капсулы → игровое событие (скриншот) → капсулы Сакуры → заметки → погода
  LLM-тексты: ask_gemini(prompt, save_history=False, chain=background) — ПОЛНЫЙ промпт персоны
ws_protocol.handle_register: приветствие (rituals, chain voice) → Telegram; брифинг (раз в день)
adapters/ws.ws_handler (отключение устройства): прощание (rituals) → Telegram
main.py: веха отношений (check_milestone) при старте
modules/reflection.reflection_loop: ночная рефлексия (23:00) и утреннее резюме
```

## 2. Фоновые циклы

| Цикл | Где | Интервал | Что делает | Что пишет |
|---|---|---|---|---|
| proactive_loop | sakura_core/proactive.py | 120±(−30…+90) с, ночью пауза 300 с | напоминания, факты, капсулы, игровые события, заметки, погода | Telegram, `proactive.json`, отметки задач/капсул |
| reflection_loop | modules/reflection.py | проверка раз в 300 с | ночная рефлексия, утреннее резюме, очистка истории | `self_memory`, `master_memory`, `session_summary.json`, `time_feeling.json`, `mood_arc.json` |
| daily_analysis | sakura_core/memory_tasks.py | раз в сутки | анализ дня LLM (7 ошибок JSON за период) | `master_memory` |
| reminder_check_loop | modules/reminders.py | 5 с | срабатывание напоминаний | голос/Telegram |
| steam_library_loop | modules/steam_integration.py | 6 ч | синхронизация библиотеки | `steam_games` |
| steam_achievements_loop | modules/steam_integration.py | 10 мин | новые ачивки | `steam_achievements_seen` |
| vps-monitor | modules/vps_monitor.py | 60 с | метрики сервера → «самочувствие» | память процесса |
| telegram-monitor | modules/tg_monitor.py (Telethon) | события | уведомления из ТГ мастера | `notifications.json` |
| discord-bot | modules/discord_bot.py | события | голос Discord + Whisper medium | — |
| warmup-tts-cache | modules/tts_server.warmup_cache | при старте | предсинтез ack-фраз | `memory/tts_cache/` |
| ensure-narrative | modules/sakura_narrative.py | при старте, кэш 24 ч | нарратив «моя история» | память процесса |

## 3. LLM-вызовы

76 мест вызова (AST-инвентаризация `tools`-скриптом аудита). Сгруппировано:

| Место (файл:функция) | Цепочка | Назначение | Частота за 15 суток (журнал) |
|---|---|---|---|
| sakura_core/router (LLM-классификатор) | chat (gemma-4-26b) | «команда или разговор» на каждый голосовой ход вне реестра | ~33 успешных |
| sakura_core/llm.ask_gemini_voice → adapters/voice.stream_llm_to_tts | voice (gemini-3.5-flash-lite) | голосовой ответ | 32 хода |
| sakura_core/llm.ask_gemini | chat по умолчанию / передаётся | текст Telegram, голосовые ветки-команды, проактив | 65 (строка `[ask_gemini time]`) |
| sakura_core/memory_tasks.extract_and_remember | background | извлечь факты из реплики чата | на каждый ход с save_history |
| modules/secret_diary.write_entry | background | дневниковая запись | на каждый ход с save_history (311 записей) |
| sakura_core/memory_tasks.summarize_session / daily_analysis | background | резюме сессии / анализ дня | по порогу / 1 в сутки |
| modules/reflection.run_night_reflection / run_morning_summary | background | ночная рефлексия, утро | 15 ночей |
| modules/briefing.run_briefing | background (через ask_gemini) | утренний брифинг | 11 |
| sakura_core/proactive.proactive_loop (4 вызова) | background (через ask_gemini) | напоминания, капсулы, заметки | 0 напоминаний за период |
| sakura_core/ws_protocol (handle_register/ping/notification/command_result/kettle) | voice | приветствие, музыка, страницы, уведомления | по событиям |
| adapters/media (фото, видео, кружки) | model=MAIN_MODEL | описание медиа | по событиям |
| modules/web_search.search_grounded | grounded | поиск с Google | 0 за период (`[search]`) |
| memory/db._embed | gemini-embedding-2 | семантический поиск памяти | 129 |
| Не вызываются вовсе (мёртвые) | — | autonomous.do_research, game_detector.detect_game_from_screenshot, chains.parse_chain_from_llm, emotional_memory.generate_spontaneous_thought | 0 |

Успешных строк `[llm] success` за период: background 39, chat (gemma) 33, voice 47.
Неудачи: попыток 34 (500/503/429/таймаут), «все модели не ответили» — 25 раз.

## 4. Таблицы БД

| Таблица | Строк | Последняя запись | Кто пишет | Кто читает | В промпт |
|---|---|---|---|---|---|
| master_memory | 234 | 09.10 | memory/db.py | db, personality (адаптация), narrative, memory_honesty, memory_validator | да (блок ПАМЯТЬ, адаптация, нарратив) |
| self_memory | 694 | 09.10 | memory/db.py (рефлексия, дневник, коррекции) | db, briefing | да (блок «что Сакура помнит о себе», брифинг) |
| secret_diary | 311 | 09.10 | modules/secret_diary.py | secret_diary, narrative | косвенно (нарратив) |
| episodes | 190 | 13.09 | modules/episodes.py | episodes, narrative, relationship | нарратив; запись отключена (EPISODES_LOG_COMMANDS=0) |
| entities / edges | 43 / 53 | 09.10 / 22.09 | modules/graph.py | graph | да (СВЯЗИ В ПАМЯТИ) |
| conversation_threads | 10 | 02.09 | modules/threads.py | threads | да (если есть открытые) |
| behavior_patterns / rec_history | 175 / 15 | — | modules/proactive_recs.py | proactive_recs | нет |
| app_usage | 51 | — | modules/app_launcher.py | app_launcher | при упоминании приложений |
| steam_games / steam_achievements_seen | 73 / 178 | 09.10 / 05.10 | steam_integration | steam_integration, voice_info | да (текущая игра) |
| sakura_capsules / capsules | 7 / 0 | 01.09 / — | capsules | capsules | нет (проактив) |
| relationship | 4 | — | relationship | relationship | вехи, близость |
| device_presence | 4 | 09.10 | presence_sync | presence_sync | косвенно (контекст) |
| japanese_vocabulary | 35 | 28.06 | learn_japanese | learn_japanese | по ключевым словам |
| habits, topic_frequency, topic_reactions, speech_patterns, voice_notes, work_sprints, joke_debt, news_digest | 0 | — | модули-писатели есть (кроме work_sprints) | те же | блоки всегда пустые |
| migrations | 2 | 03.07 | db | db | нет |
| vec_master, vec_self (+служебные) | — | — | db (sqlite-vec) | db (семантический поиск) | через ПАМЯТЬ |

Восемь таблиц пусты с момента создания — функции, которые их наполняют,
не подключены или не срабатывают (подробнее — 05-code-health.md).
