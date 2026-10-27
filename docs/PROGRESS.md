# Browser agent — сервер (server/browser-step)

Общий контракт: Сакура ведёт в браузере длинные сценарии (формы, онлайн-тесты);
сервер держит состояние задачи и решения моделей Gemma 4, desktop ведёт цикл
шагов, расширение исполняет. Здесь — ход работ серверной части.

## S0. Живая проверка Gemma 4 (scripts/probe_gemma.py)

Запуск вручную: `venv/bin/python scripts/probe_gemma.py [--burst 20] [--only …]`.
Прогон 2026-10-26 ~21:00–21:45 MSK, один ключ (активный из config), обе модели
параллельно, темп ≈13 RPM на модель; 500/503 повторялись до 3 раз, 429 — по
retryDelay. Строки, где первый прогон упал только на 500 (у 31b: картинка,
3 кадра, AUTO, schema, JSON, temperature, top_p, system_instruction; у 26b:
temperature=0.0, max_output_tokens), перепроверены вторым прогоном (`--only`,
21:46) — все ✅; в таблице итог. Всего ≈140 вызовов.

| проверка | gemma-4-26b-a4b-it (навигатор) | gemma-4-31b-it (решатель) |
|---|---|---|
| картинка + текст | ✅ 17 с | ✅ 44 с |
| 3 кадра в одном запросе | ✅ порядок верный, 61 с | ✅ порядок верный, 46 с |
| function calling, mode ANY | ✅ `page_act(ref, action, note)`, 29 с | ✅ 33 с |
| function calling, mode AUTO | ✅ (вызов, не текст), 75 с | ✅ (вызов, не текст), 60 с |
| response_schema `{reasoning, answer}` | ✅ 70 с | ✅ 32 с |
| response_mime_type JSON | ✅ | ✅ |
| temperature | ✅ (0.0 и 1.0) | ✅ (0.0 и 1.0) |
| top_p / top_k | ✅ / ✅ | ✅ / ✅ |
| max_output_tokens | ✅ (но см. «мысли») | ✅ |
| system_instruction | ✅ | ✅ |
| stop_sequences, seed, candidate_count=1 | ✅ | ✅ |
| safety_settings (OFF) | ✅ | ✅ |
| thinking_level=minimal | ✅ — мысли выключаются (thoughts=None) | ✅ — то же |
| thinking_budget | ❌ 400 «Thinking budget is not supported» | ❌ 400 |
| presence/frequency_penalty | ❌ 400 «Penalty is not enabled» | ❌ 400 |
| response_logprobs | ❌ 400 «Logprobs is not enabled» | ❌ 400 |
| 20 запросов разом | 7 ok, 12× 500, 1 таймаут (90 с); **429 нет** | 7 ok, 13× 500; **429 нет** |

Выводы:
- **Задержка.** 17–77 с на вызов даже для «Say hi» (вечер 26.10, бэкенд под
  нагрузкой). Шаг навигатора — десятки секунд; последовательный агент не
  выходит и за ~3 RPM на модель, так что RPM 15 на практике не упор, упор —
  RPD 1500 и задержка. 200 шагов × ~40 с ≈ 2 ч > 1800 с — поэтому лимит
  времени по умолчанию снят (`BROWSER_MAX_SECONDS=0`, DECISIONS B27).
- **500 INTERNAL — частые** (до половины запросов в пиках, у 31b больше, чем у
  26b). Отсюда повторы 500/503 в `llm.generate_agent` и `wait 15 с` на desktop
  (DECISIONS B9).
- **429 не получен**: при 20 параллельных запросах бэкенд отвечает 500, а не
  429, — фактический RPM/RPD этим прогоном не измерен; формат 429
  (RetryInfo/QuotaFailure) взят из документации Gemini API и закрыт тестами.
  Ориентир 15 RPM / 1500 RPD оставлен в config (`GEMMA_RPM`, `GEMMA_RPD`).
- **Мысли.** Gemma 4 думает по умолчанию (20–160 thought-токенов) и мысли
  входят в `max_output_tokens`: 26b с лимитом 32 один раз вернула пустой
  ответ. У навигатора и решателя лимит 2048 (512 в режиме таймера).
  `thinking_level=minimal` мысли выключает — рычаг задержки на будущее; в
  `GEMMA_PARAMS` thinking_config не включён (DECISIONS B18).
- **GEMMA_PARAMS** (config): system_instruction, max_output_tokens, temperature,
  top_p, top_k, stop_sequences, seed, candidate_count, safety_settings,
  response_mime_type, response_schema, tools, tool_config,
  automatic_function_calling.

## Повторный замер: задержка навигатора и thinking_level (27.10)

`venv/bin/python scripts/probe_gemma.py --nav-latency 5` — настоящий запрос
навигатора (`build_request`: цель, журнал из 2 шагов, кадр 640×400, снимок
с 8 элементами и текстом, 14 инструментов, function calling mode ANY;
≈2400 входных токенов), 5 пар «мысли по умолчанию / thinking_level=minimal»
попеременно, 27.10 ~20:55–21:01 MSK. Ок = ответ с вызовом инструмента после
до 3 повторов 500/503.

| модель | режим | ок | медиана, с | мин–макс, с | thoughts | повторов 500/503 |
|---|---|---|---|---|---|---|
| gemma-4-26b-a4b-it | по умолчанию | 5/5 | 3.5 | 1.4–37.4 | 0 | 3 |
| gemma-4-26b-a4b-it | minimal | 5/5 | 23.8 | 2.0–49.0 | 0 | 1 |
| gemma-4-31b-it | по умолчанию | 4/5 | 12.1 | 5.4–32.9 | 0 | 3 |
| gemma-4-31b-it | minimal | 4/5 | 19.7 | 4.5–24.9 | 0 | 6 |

Выводы:
- **С принудительным function calling Gemma не думает ни в одном режиме**
  (thoughts = 0 во всех 20 ответах), поэтому `thinking_level=minimal` на
  задержку навигатора не влияет: разница медиан — шум бэкенда (разброс внутри
  режима 1.4–49 с, выборка 5 на режим). Мысли (20–160 токенов, S0) появляются
  только в запросах без инструментов — у навигатора это сжатие журнала.
  `BROWSER_NAV_THINKING=minimal` оставлен по ТЗ: для навигатора он нейтрален,
  для сжатия журнала убирает мысли.
- **Режим меняет решение**: на одном и том же запросе «по умолчанию» все 9 удачных ответов
  выбрали `page_forms` (≈25 токенов), minimal — все 9 удачных `page_fill_form`
  сразу (≈65 токенов). Обе тактики допустимы; на качество навигации это стоит
  проверить на реальных формах.
- **Бэкенд сегодня быстрее, чем 26.10**: типичный ответ навигатора 2–25 с против
  17–80 с вчера, но хвосты до 50 с и 500/503 остаются (у 31b — 2 из 10 запросов
  не дали ответа и после 3 повторов). Повторы 5→10→20 с с переходом по цепочке
  (DECISIONS B26) — по делу.

## Статус по пунктам

| пункт | статус | где |
|---|---|---|
| S0 probe | ✅ выполнен первым, итог выше | scripts/probe_gemma.py |
| S1 конфиг | ✅ | config.py |
| S2 лимитер RPM/RPD | ✅ token bucket на модель, RPD до полуночи PT, `data/gemma_quota.json` | sakura_core/rate_limiter.py |
| S3 429 | ✅ retryDelay → 4/8/16/32/32 с → следующая модель → paused + Telegram + автопродолжение | sakura_core/llm.py (`generate_agent`), browser_step.py |
| 500/503 | ✅ 5→10→20 с → модель выведена на 60 с → следующая → paused «Gemma не отвечает», автопродолжение (27.10) | llm.py, rate_limiter.py |
| S4 фильтр параметров | ✅ gemma-* по `GEMMA_PARAMS` + thinking_config только с thinking_level (27.10), gemini-3.5-flash-lite без temperature/top_p | sakura_core/llm.py (`filter_params`) |
| S5 BrowserTask | ✅ чекпоинт без кадров/текста, восстановление, одна задача на окно | sakura_core/browser_task.py |
| S6 навигатор | ✅ FC + разбор JSON, note обязательна, окно кадров, сводка, автоскрин; `BROWSER_NAV_THINKING=minimal` (27.10) | sakura_core/browser_step.py |
| S7 решатель | ✅ schema, все kind, кадр-вырезка, режим таймера, изоляция; пакеты до `QUIZ_PARALLEL=3` через лимитер (27.10) | sakura_core/quiz_solver.py, browser_step.py |
| схема инструментов | ✅ `scripts/export_tool_schema.py` → формат фикстуры desktop, снимок tests/fixtures/server_tools.json (27.10) | browser_step.TOOL_SPEC |
| S8 формы/тесты/капча | ✅ | browser_step.py |
| S9 управление и отчёт | ✅ browser.task / browser.stop, прогресс (орб `status.activity` + одно сообщение Telegram), отчёт | capabilities/browser_agent.py, bridge.py |
| S10 подтверждения | ✅ за флагом | browser_step.py, bridge.py |

Тесты: tests/test_gemma_params.py, tests/test_gemma_quota.py,
tests/test_browser_agent.py, tests/test_browser_capability.py,
tests/test_tool_schema.py. Полный прогон (27.10: 1237 passed) —
всё зелёное, кроме `test_acks.py::test_cache_key_changes_with_model_or_voice`
(падал и на master до этой ветки).

## Что нужно от desktop и расширения (сверить)

- `browser.do` с `resume: true` и прежним task_id — продолжить шаги (после паузы
  по квоте; DECISIONS B6).
- Повтор шага после `status: wait` — с тем же `step` (B8).
- `page_questions` → `last_result.detail.questions[...]`; `page_shot {crop_ref,
  q_index}` → кадр `kind: question`; поля `invalid`/`error` и `type` у элементов
  (B12).
- Ответ сервера на шаг может идти десятки секунд (задержка Gemma) — таймаут
  ожидания на desktop не меньше 5 минут.
- Схема инструментов: `scripts/export_tool_schema.py` → положить в
  desktop/tests/fixtures/server_tools.json (формат — DECISIONS B28); спека
  поменялась — снимок в tests/fixtures/ и тест `test_tool_schema` это покажут.
- Пакет ответов теста приходит одним `page_fill_form` с полями нескольких
  вопросов (B25).
- Включение: `BROWSER_AGENT=1` на сервере; канал — Noise/локальный (приватный
  класс `browser*`).
