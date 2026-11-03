# Прогресс автономной задачи (сервер)

Начало: 2026-10-15 21:13 (по часам VPS). Прод не трогается; ветки от
origin/master (2a9e6a3 на старте); push только своих веток.

## Журнал

| время | блок | состояние |
|---|---|---|
| 10-15 21:16 | I.1 документы | `docs/security/THREAT_MODEL.md`, `PROTOCOL.md` запушены (feat/securechannel 99a3baa) — клиент может реализовывать |
| 10-16 ~08:00 | I.2 реализация | securechannel/: учебный Noise (совпадает с официальными векторами IK и XXpsk3), обёртка noiseprotocol, кадры, канал с rekey, ключи, реестр, спаривание, лимиты, сервер, эталонный клиент; сквозной прогон: спаривание, сеанс 300 КБ, неизвестный ключ — тишина и 4408 ровно через 5 с |
| 10-16 08:20 | I.3 интеграция | adapters/ws.py: SECURE_CHANNEL off/optional/required, device_id из реестра, secure = Noise или локальный источник, приватные классы только secure; весь набор 979 passed |
| 10-16 09:10 | I.4 тесты | 85 тестов securechannel (векторы, дифференциальные, негативные, hypothesis, фаззер, сервер, ws_handler), покрытие 95%; весь набор 1068 passed |
| 10-16 09:20 | I.2/I.4 доп. | /pair /devices /revoke, scripts/secure_recovery.sh, KEYS.md, FORMAL.md + proverif/ik.pv (не запускалась), DEFENSE_A.md (40 вопросов); feat/securechannel bb5b927 |
| — | I.5 (опц.) | шифрование в покое — отложено в конец |
| 10-16 08:43 | II.А proto-v2-rest | журнал чата перенесён на новое ядро; memory_*, profile_* (на лету), сценарии v1 (движок, confirm при запуске, ≤ 20 шагов); приватные классы и кадры экрана только secure; 1049 passed; feat/proto-v2-rest 1dcd5d4 |

## server/multidevice (2026-10-20)

| блок | состояние |
|---|---|
| integration | server/integration: securechannel + proto-v2-rest + server-autonomy влиты; найден и исправлен `noiseprotocol` в requirements; 1114 passed |
| 2 KNOWN_DEVICES | из `DEVICES` (pc, laptop, mostech, phone); неизвестный id показывается как есть |
| 3 активное устройство | одна функция в presence_sync; голос/текст — сразу, `input_idle_s`, пороги 5/30 с, старая логика без поля |
| 4 треки | по устройствам, замена целиком; в промпт — активного, иначе свежий играющий ≤ 60 с |
| 5 secure_devices | master + secure; без ключей и PSK |
| 6 presence | proto 2 — presence, proto 1 — флаги; `MOOD_BROADCAST=off` |
| 7 docs | PROTOCOL.md §10, DECISIONS M1–M15, RUNBOOK_MULTIDEVICE.md |
| тесты | tests/test_multidevice.py (17); весь набор 1131 passed |

Не сделано / вне задачи: клиент не шлёт `input_idle_s` (agent/ и desktop/ не трогались); прод не перезапускался.

## server/presence-memory (2026-10-20)

| блок | состояние |
|---|---|
| 1 очистка | `scripts/cleanup_tasks.py` (+`--dry-run`), `/забудь_задачи` с «Да/Нет»; копия в `memory/backup/<дата>/` |
| 2 не копить | задачи только по «напомни…»; нити `THREADS=off`; напомненные/выполненные не в промпте; просрочка > 24 ч → `memory/tasks_archive.json` |
| 3–4 присутствие | `presence_sync.get_master_presence()` (at_pc/at_work/away_from_pc/pcs_off), сообщение `bye` (PROTOCOL.md §10.5–10.6) |
| 5 промпт | реальное присутствие в блоке контекста, директива «Он не у компьютера…», окно не даёт «играет» вне ПК |
| 6–7 вывод | проактив при away/pcs_off — только Telegram; «Устройство X недоступно» для ПК убрано |
| тесты | tests/test_presence_memory.py (19), весь набор 1153 passed |

### Как запустить очистку на проде (не выполнялось)

Из `/opt/sakura`, тем же python, что у сервера; **сначала dry-run**:

```
cd /opt/sakura
venv/bin/python scripts/cleanup_tasks.py --dry-run     # только покажет: сколько и первые 40 символов
venv/bin/python scripts/cleanup_tasks.py               # копия в memory/backup/<дата>/ → очистка
```

Или в Telegram: `/забудь_задачи` → «Да». Откат: вернуть `tasks.json` из
`memory/backup/<дата>/` и открыть нити (`UPDATE conversation_threads SET closed=0`
по `conversation_threads.json` из той же папки). Остановка сервера для очистки не нужна;
лучше запускать, пока никто не говорит с Сакурой.

Клиентам: `bye` (shutdown/sleep/exit) и `input_idle_s` в ping шлёт агент — `agent/`
не менялся, до обновления агента действует запасная логика (последний голос/текст).

## server/power (2026-10-20)

| блок | состояние |
|---|---|
| 1 реестр | `system.shutdown`, `system.restart`, `power.sleep` — confirm: true; `system.sleep` → legacy `power.sleep`, фразы слиты |
| 2–3 вопрос и ответ | `sakura_core/power_confirm.py`: явный вопрос с названием ПК, `reply kind=confirm`, ответ голосом/текстом/кнопками Telegram, срок 60 с |
| 4 выбор ПК | по названию в фразе, «все компы», активный; офлайн — «уже выключен» |
| 5 исполнение | команда с `confirmed: true` целевому ПК |
| 6 bye/офлайн | висящий вопрос сбрасывается |
| тесты | tests/test_power_confirm.py (12); обновлены устаревшие; весь набор зелёный |

Перед выкаткой: проверить на старом `agent/`, что `power.sleep` и `system.shutdown` с `confirmed`
исполняются (до этого он получал `system:shutdown`/`system:sleep`).

### server/power: правки перед выкатом

- Вопрос о питании снимается любым ходом кроме да/нет и любым другим вопросом Сакуры (W11–W12);
  «да» из Telegram через 10 с по-прежнему подтверждает.
- proto 1 получает `system:shutdown/restart/sleep`, proto 2 — канонические + `confirmed` (W13).
- «Какой компьютер: …?» при неоднозначности (W14).
- Тесты: tests/test_power_confirm.py — 20; весь набор зелёный.


## Выкат на прод (2026-10-21)

- Хэш до выката (откат: `git checkout 2a9e6a3d8f1a8aaef5b363846bfdd8e356d3ba1e`, `systemctl restart sakura`): **2a9e6a3d8f1a8aaef5b363846bfdd8e356d3ba1e**.
- Резервная копия `memory/` — `memory/backup/predeploy-<дата>/` на проде.
- Конфигурация проверена (True/False): PRIVATE_REQUIRES_SECURE не выключен, mostech в MASTER_DEVICES, SECURE_CHANNEL отсутствует/off.

### Выкат fix/active-pc-only (2026-10-21)

- Хэш до выката (откат: `git checkout 1b6f189d0ba99b2a346980078bc887898d3bc7bb`, `systemctl restart sakura`): **1b6f189d0ba99b2a346980078bc887898d3bc7bb**.
- Причина: на проде телефон стал «активным устройством» (`Фокус переехал: none → phone`); теперь активным может быть только ПК.

## Зрение (feat/vision, 2026-11-01)

| пункт | что сделано |
|---|---|
| транспорт | `sakura_core/vision/capture.py`: `vision.capture` → ожидание `vision.frame` (5 с), features в `register`, снятие при отключении |
| вопрос | `vision.ask` (бывший `screenshot.describe`): «глянь на экран» → кадр → `VISION_MODEL_CHAIN` → ответ на ход; старый клиент — через `command_result` |
| взгляд | `vision/glance.py` + фоновая задача `vision_glance` в `main.py`; `vision.glance.on/off` |
| память | `vision/seen.py` → `modules/context.get_screen_context()` |
| анти-повтор | `modules/repeat_guard.py` |
| удалено | анализ `screen_context` (`apps.analyze_screen_context`, `_analyze_screen_context` в ctx), прямой вызов модели в ветке describe |
| исправлено | «что у меня на экране» → фото в Telegram вместо описания (V6) |
| реестр | 122 → 124; golden — точечно (V16) |
| тесты | `tests/test_vision_{capture,ask,glance,parse}.py` — 94; мутационная проверка: снятие secure-проверки, проверки перед репликой и `need_change` роняют тесты |

Прогон: PyPI в сессии разработки был закрыт — набор гонялся с заглушками `google.genai/aiogram/websockets`.
Новых падений относительно master нет (150 падений окружения одинаковы до и после), тесты зрения, реестра,
golden, промпта — зелёные. **Перед выкатом: полный `pytest` в боевом venv.**

Перед включением на проде:
- клиент `desktop/` с `vision.capture` (ТЗ-2, ветка `feat/vision-client`); до него `vision.ask` работает через старый путь, взгляд не планируется;
- `VISION_GLANCE` по умолчанию `1`, но сам взгляд выключен до голосового «поглядывай на экран».

### Выкат feat/vision

- Хэш до выката (откат: `git checkout 8dc9e6cea188643c058a8a808449b33f7f129255`, `systemctl restart sakura`): **8dc9e6cea188643c058a8a808449b33f7f129255**.
- Перед перезапуском: резервная копия `memory/`, полный `pytest` в боевом venv (в разработке прогон шёл на заглушках).
- Новых зависимостей и переменных окружения, обязательных к заданию, нет; взгляд выключен до «поглядывай на экран».

## Поиск: единый конвейер (feat/search-core, 2026-11-01)

- `sakura_core/search/`: context, plan, rank, pages, pipeline; docs/SEARCH.md; DECISIONS Q1–Q8.
- Переведены: `ask_gemini`, `ask_gemini_voice`, `vision.ask`, `tg_share`, `search_and_fetch`/`smart_search` (автономные исследования).
- Убран «поиск из памяти модели».
- Тесты: `tests/test_search.py` (25) — тема по окну против догадки зрения, план, судья, дочитка, сценарий «хлопок»; переписаны `test_tg_share`, `test_vision_ask` под конвейер. Регрессия: новых падений нет.
- Проверить на проде: строки `[search] канал=…` в журнале (время шагов, отобрано/найдено).

## Поиск: SearXNG (feat/search-searxng, 2026-11-01)

- `sakura_core/search/providers.py`: parallel + searxng, `merge`/`norm_url`, `fetch_all` (сбой одного не мешает); конвейер зовёт `providers.fetch_all`; DECISIONS Q9–Q11.
- Установка: `deploy/searxng/` (compose, settings.yml), `scripts/install_searxng.sh`; в `.env`: `SEARXNG_URL=http://127.0.0.1:8888`.
- Тесты: +6 в `tests/test_search.py` (разбор ответа, слияние, включение, отказ поставщика, параллельные запросы).
- Живой запуск контейнера — на VPS (в среде разработки нет Docker-демона).

## Агент браузера влит (feat/browser-integration, 2026-11-02)

- server/browser-step влит поверх зрения и поиска; конфликты — config.py, DECISIONS, счётчики реестра (126 деклараций, vps 31).
- Выключен до `BROWSER_AGENT=1`. Клиентская часть (расширение 3.2.0) — в feat/vision-client.
- Регрессия на заглушках (genai.types теперь записи): master 102 падения окружения = после слияния 102; тесты агента 240 passed.
- После проверки на проде убрать тестовые инстансы `sakura-test`/`sakura-test2` (8767/8768, `PRIVATE_REQUIRES_SECURE=0`) и временные правила ufw.

## Замер решателя тестов (feat/quiz-eval, 2026-11-02)

- `eval/quiz/bank.json` (97), `sakura_core/quiz_eval.py`, `scripts/quiz_eval.py`, docs/QUIZ_EVAL.md, DECISIONS E1–E4.
- Тесты: `tests/test_quiz_eval.py` (12) — согласованность набора, эталон через validate решателя, частичные ответы, числа/текст, кадры, прогон с поддельным решателем, ожидание квоты, сравнение, `--dry-run`. Кадры просмотрены глазами.
- Живой прогон — на VPS (ключ API только там).

## Решатель: таймауты и кадры (fix/quiz-solver-speed, 2026-11-02)

- Первый замер (Gemma 4, 97 вопросов): 30,9%, сбоев 67 (неверных ответов нет), вызов p50 120,0 с, прогон 96 мин.
- Исправлено: async-клиент в `generate_raw` (E5), кадр только при картинке (E6), текст варианта вместо ref (E7); в отчёте замера — причина сбоя и сырой ответ; `--crop media|all`.
- Тесты: +4 (кадры по правилу, текст вместо ref, raw в SolveError, отмена запроса по таймауту); 3 теста механики кадра — с `QUIZ_CROP=all`. Регрессия: 102 = 102.
- Ждёт: повторный замер на VPS.

## Решатель: формат ответа (fix/quiz-json, 2026-11-02)

- Замер №2 (после E5–E7): 85,6%, сбоев 12 (все — разбор JSON), неверных 2 (ord-05, inj-01); вопрос p50 4,2 с, p90 114 с; прогон 24 мин.
- Исправлено: E8–E10. Тесты +3. Регрессия: без новых падений.
- Ждёт: замер №3.

## Решатель: время (fix/quiz-timing, 2026-11-02)

- Замер №3 (E8–E10): 99,0%, единственная ошибка — mch-02 (MAX_TOKENS дважды); прогон 36 мин, вопрос p50 44 с, вызов p50 8 с, 216 вызовов.
- Сделано: E11–E13. Тесты +2. Регрессия без новых падений.
- Ждёт: замер №4 — с температурой по умолчанию и с `--temperature 0.3`, сравнение.

## Решатель: быстрая модель первой (feat/quiz-fast, 2026-11-02)

- Замер №4: 100% / 100% (t по умолчанию / 0,3), прогон 23–24 мин; генерация 3461 с, ожидание 505 с (почти всё — паузы после 500/503); 26b — 2–4 с на вопрос, 31b — 10–110 с.
- Сделано: E14–E16. Тесты +2, переписан тест лимитера под быстрое переключение. Регрессия без новых падений.
- Ждёт: замер №5.

## Решатель: потолок токенов (perf/quiz-tokens, 2026-11-03)

- Замер №5: 99,0%, 747 с (−46%), p50 4,1 с, p90 59 с; хвост — 19 вопросов с обрывом первой попытки на 2048 токенах.
- Сделано: E17, `--max-tokens` в замере. Ждёт: замер №6.


## Верификация securechannel (docs/crypto-verification)

| время | шаг | состояние |
|---|---|---|
| 10-29 | модели | `docs/security/proverif/ik.pv` переписана по PROTOCOL §3.1–3.2 (AD = h, nonce, Split, KCI-сервер K, устройство атакующего, фаза 1); новая `xxpsk3.pv` (§3.3, QR и «только слова», weaksecret). Синтаксис сверен с грамматикой ProVerif 2.05 чтением, **не запускались** |
| 10-29 | векторы | `scripts/gen_interop_vectors.py` → `securechannel/vectors/interop.json`: IK и XXpsk3, фиксированные ключи, транспорт и rekey; `tests/test_securechannel_interop.py` (lib, edu и смеси) — 18 passed |
| 10-29 | документы | FORMAL.md §0: таблица «свойство → модель → ожидаемый → фактический» (фактический = «ожидает запуска»), §3.2 уточнён (офлайн-перебор без QR); `results/README.md` с командами; DECISIONS CV1–CV11 |
| — | запуск ProVerif | ждёт владельца: `results/ik.txt`, `results/xxpsk3.txt` → затем фактические результаты и разбор атак в FORMAL.md |

## Агент: транспорт Noise (feat/agent-securechannel, 2026-10-29)

Перенесено из локальной ветки владельца. Весь трафик `agent/core/agent.py` идёт
через `core/transport.py` (Noise IK поверх того же `ws://`), token — только на
старом транспорте. Решения — DECISIONS A1–A16.

| блок | состояние |
|---|---|
| `transport.open_connection` / `Conn` | `send`, `send_json`, `recv`, `async for`, `close`, `secure`, `transport`, `close_code` |
| Noise | `securechannel.client.connect_session`, таймаут 10 с, ошибки → `SecureHandshakeFailed`; отката на token нет |
| исходящий трафик | все отправки агента и `outbox.flush` — через `Conn.send_json` |
| ротация ключа сервера | `secure_server_key` → `set_next_server_pub` (только по Noise); `promote_next` |
| коды закрытия | 4408/4409 — backoff; 4412 — ожидание ключей; 4413 — очередь очищена, 60 с |
| статус | 🔒 в оверлее и трее из `conn.secure` |
| хранилище ключа | ТЗ-4: `core/secure_store.py` в master (CV20) |

Тесты (Windows, Python 3.11, на момент ветки): `python -m pytest agent/tests -q` — 228 passed;
`test_transport.py` (22) — против настоящего `securechannel.server.accept`, проверено
мутацией (с откатом на token падают 6 тестов). После ТЗ-4 (Windows, 2026-11-04):
`test_secure_store`, `test_agent_pairing`, `test_tray_pairing`, `test_transport` —
39 passed, 1 skipped (POSIX-права), настоящий DPAPI — пройден.

## Крипта: интеграция и CI (2026-11-03)

| шаг | состояние |
|---|---|
| merge `docs/crypto-verification` | модели ik.pv/xxpsk3.pv, интероп-векторы; решения перенумерованы V → CV (V занято зрением) |
| merge `feat/agent-securechannel` | транспорт Noise IK в `agent/`, фикс `requirements-dev.txt`; тесты канала агента 40 passed, собираемый набор `agent/` 225 passed (Linux, без Qt-оверлеев и GigaAM) |
| `agent/`: тихий снимок экрана | удалён (CV15), страж падает на прежнем коде |
| CI | `.github/workflows/securechannel.yml`: тесты securechannel + сверка (114 passed в чистом venv), векторы `--check`, ProVerif → ветка `ci/proverif-results` |
| выкат | `docs/security/ROLLOUT.md` (off → optional → спаривание по QR → required → вывод WS_SECRET); блокер `required` — ТЗ-4 (хранилище ключей agent/) |
| ProVerif, запуск 1 (`a35ceb1`) | полные модели — тайм-аут 3000 с; xxpsk3 Q1–Q6 совпали; разбор — FINDINGS F1 |
| ProVerif, варианты (CV17) | `ik_core` 8/8 и `xxpsk3_auth` 8/8 совпали с ожидаемыми (CI `3ccc9d7`: 5:08 и 5:12; сырой вывод в `results/`) |
| открыто | ik Q8/Q9 (KCI), сценарий D, weaksecret xx Q7/Q8 — CV18 |
| ТЗ-4 (`feat/agent-pairing`) | `core/secure_store.py` (DPAPI + icacls), `core/pairing.py` (QR/слова против `securechannel.client.pair`), трей «Спарить…»/«Сбросить», переподключение без рестарта; зависимости и `build.bat`; тесты `agent/` 249 passed, 1 skipped (Linux, без Qt-оверлеев и GigaAM; DPAPI — только на Windows) |
| выкат (2026-11-04) | VPS: `SECURE_CHANNEL=optional` (откат — `e85ed0b`), `memory/secure` 700, файлы 600; desktop на ПК спарен, `SERVER_TRANSPORT=noise-only` — «Зашифровано» |
| долги тестов (до 2026-11-04, не связаны с U1–U9) | `tests/test_voice_perf.py::test_early_gate_rules` и `…question_does_not_wait_for_verdict` — красные и на `e85ed0b`; `test_voice_info` в песочнице без `tkinter`; vitest desktop на Windows — нестабилен |
| ждёт | живые проверки «глянь на экран» и голоса (U6); спаривание телефона → `required` и вывод `WS_SECRET` (ROLLOUT шаги 3–4); запрет отката `noise`→`ws` у спаренного desktop |
| единый клиент (`feat/unified-client`) | desktop слит в master (U1–U6); desktop-ci на Windows: ядро 1075 passed, интерфейс — зелёный |

