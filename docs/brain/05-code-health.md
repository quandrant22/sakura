# 05. Здоровье кода

Срез master `6f0fb74`. Ничего не удалялось. Импортёры искались по всему
коду, кроме venv/agent/docs; «динамика» — упоминание в `importlib`/`__import__`
строкой; «реестр» — упоминание в `capabilities.yaml`.

## 1. Кандидаты на удаление (15)

| # | Путь | Строк | Кто импортирует/вызывает | Динамика / реестр | Тесты | Комментарий |
|---|---|---|---|---|---|---|
| 1 | `modules/youtube.py` (весь модуль) | 285 | никто | нет / id `youtube.*` есть в реестре, но исполняет агент | нет | команды YouTube ушли в агент и расширение |
| 2 | `modules/prompt_builder.py` (весь модуль) | 256 | никто | нет / путь упомянут строкой в подсказке «КОДИНГ» (`sakura_core/prompt._coding`) | нет | сначала убрать упоминание из подсказки |
| 3 | `modules/tts_server.py: stream_llm_to_tts` (v2) | ~80 | никто (голос идёт через `adapters/voice.stream_llm_to_tts`) | нет | нет | дублирует имя голосового адаптера, путает поиск |
| 4 | `modules/tts_server.py: _synthesize_stream` | 51 | никто | нет | нет | старый путь до двухстадийного синтеза |
| 5 | `modules/tts_server.py: add_emotion_pauses` | 4 | никто | нет | нет | пустышка («говорим дословно») |
| 6 | `modules/state_arbiter.py: get_state_block` | 121 | только тесты | нет | 5 ссылок | блок состояния, не вошедший в промпт |
| 7 | `modules/autonomous.py: do_research`, `should_do_research` | 96 | никто | нет | нет | LLM-вызов «исследования»; `news_digest` пуста |
| 8 | `modules/proactive_recs.py: get_recommendation` | 73 | никто | нет | нет | рекомендации не отправляются; `rec_history` не растёт |
| 9 | `modules/game_detector.py: detect_game_from_screenshot` | 56 | никто | нет | нет | мёртвый LLM-вызов (vision) |
| 10 | `modules/chains.py: parse_chain_from_llm` | 44 | никто | нет | нет | мёртвый LLM-вызов |
| 11 | `modules/reflection.py: get_time_feeling_hint` | 43 | только тест | нет | 1 | «ощущение времени» не попадает в промпт |
| 12 | `modules/evening_pulse.py: should_send_pulse`, `get_pulse_prompt` | 50 | никто | нет | нет | вечерний пульс не подключён (`last_pulse_date` = null); остальной модуль используется (`check_pc_health`) |
| 13 | `modules/relationship.py: get_growth_journal_prompt`, `should_write_journal` | 40 | никто | нет | нет | журнал роста не подключён (`last_journal` 04.08) |
| 14 | `modules/emotional_memory.py: generate_spontaneous_thought` | 22 | никто | нет | нет | мёртвый LLM-вызов |
| 15 | `modules/habits.py: get_habit_trend` и наполнение `habits` | 42 | никто; таблица `habits` пуста | нет | нет | блок «привычки» в промпте всегда пуст — удалить блок или подключить сбор |

Ещё без вызовов (мелкие, проверить вручную): `modules/proactive.get_silence_context`,
`should_skip_by_probability`; `modules/app_launcher.get_smart_default`,
`get_usage_stats`; `modules/memory_honesty.get_memory_confidence`;
`modules/disposition.desire_hint`; `modules/fears.get_fear_context`;
`memory/memory.migrate_vectors` (разовая миграция). Всего функций верхнего
уровня без ссылок — 110 (часть — обработчики Discord через декораторы,
`on_message`/`join_voice` — ложные срабатывания).

Пустые таблицы без живых писателей или с неподключёнными писателями:
`habits`, `topic_frequency`, `topic_reactions`, `speech_patterns`,
`voice_notes`, `work_sprints` (писателя нет вовсе), `joke_debt`, `news_digest`.

## 2. Дубликаты логики

| Что | Где | Риск |
|---|---|---|
| Два классификатора времени суток | `modules/context.get_time_of_day` и `personality._get_time_situation` | разные метки в одном промпте |
| Три источника «где Мастер» | расписание в персоне, `context.get_location_context`, факты памяти | противоречия («на работе» / «дома») |
| Два `stream_llm_to_tts` | `adapters/voice.py` (боевой) и `modules/tts_server.py` (v2) | путаница при правках |
| Дневник дважды | `secret_diary` и `self_memory` с тегом `diary` (по 311 записей) | двойная запись, лишний объём |
| Три независимых лимита инициативы | `proactive.json`, `rituals.json`, `briefing.json` | нет общей квоты |
| `strip_tone` | `modules/tts_server.strip_tone` и обёртка `sakura_core/llm._strip_tone` | мелко |
| Правила «никогда» | разделы КАК ТЫ ГОВОРИШЬ и НИКОГДА в персоне | +1 000 символов |

## 3. Мёртвые ветки

- `personality.get_adaptation_context`: фолбэк на `memory/long_term.json` (4.7 МБ, миграция в SQLite 03.07) — файл больше не пишется.
- `proactive_loop`: ветка «напоминания задач» — `tasks.json` содержит одну просроченную задачу с июня, новых нет.
- `memory/db._maybe_evict`: фильтр `pinned=0` — закреплённых записей 0.
- `sakura_narrative`: «Из того что помню» после EPISODES_LOG_COMMANDS=0 и фильтра команд всегда пусто (все 190 эпизодов — команды).

## 4. Захардкоженные числа и пороги

| Значение | Где | Что |
|---|---|---|
| 120 ± (−30…+90) с, 300 с ночью, 15 с, 30 с | `sakura_core/proactive.proactive_loop` | ритм проактива |
| 23 / 7 | `proactive_loop` | тихие часы |
| `_PROACTIVE_MAX_ATTEMPTS = 3` | proactive | попытки напоминания |
| 50 | `memory/db._maybe_evict(max_per_cat=50)` | ёмкость категории памяти |
| 8.0 с | `memory/db._CACHE_TTL` | кэш блока памяти |
| 30 дней | `memory/db._eviction_score` | затухание свежести |
| 86 400 с | `sakura_narrative._CACHE_TTL` | нарратив |
| 9–17, 17–18, 18–21, месяцы вуза | `personality._get_time_situation` | расписание Мастера в коде |
| 10 мин, 6 ч | steam_integration | опрос Steam |
| 300 с | `reflection_loop` | проверка рефлексии |
| 200 символов, 2 предложения, 25 символов | tts_server (настраиваемы константами) | стадии озвучки |
| 0.7 с, 2.5 с | агент (клиент) | пауза/страховка — вне сервера |

Рекомендация: вынести ритм проактива, тихие часы, ёмкость памяти и
расписание Мастера в `config.py` (env) — это первые кандидаты на настройку
владельцем.
