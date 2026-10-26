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
  RPD 1500 и задержка. 200 шагов × ~40 с ≈ 2 ч > `BROWSER_MAX_SECONDS=1800`:
  при такой задержке задача упрётся в лимит времени раньше лимита шагов.
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
