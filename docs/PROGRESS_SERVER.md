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

## server/phone (2026-10-26)

| блок | состояние |
|---|---|
| старт | ветка `server/phone` от origin/master (8dc9e6c) |
| базовая линия | не снята: Python 3.12 на машине не найден (`py -0` видит только 3.11), блоки S1–S7 не начаты |
| базовая линия (8dc9e6c + журнал) | Python 3.12.3 (как на проде), venv вне репозитория; `pytest tests/ -q`: **1199 passed, 1 skipped, 0 failed** (падений нет); `ruff check .` без конфига: **2056** замечаний (по файлам сохранено, сравнение «не хуже базы» после каждого блока) |
| S1 исполнитель phone | 14 действий `phone.*` (`executor: phone`, confirm: false, followup: ack), `capabilities/phone.py`, `PHONE_DEVICES`; офлайн → «Телефон не на связи» (reply kind=error), без очереди; pytest **1231 passed**, ruff 2056 (= база) |
| S4 SECURE_ONLY_MASTERS | `ws_auth.is_master_device(device_id, websocket=None)`: для phone (env `SECURE_ONLY_MASTERS`, по умолчанию phone) master только при `websocket.secure is True`; `proto_v2._is_master(…, websocket)`; токен/loopback/xray master-прав не дают; pytest **1236 passed**, ruff = база |
| S3 speak:false | `Turn.speak`; в `voice_command` и `chat_send` с `speak:false`: reply и chat_message есть, tts_chunk/tts_end нет, Live-сессия (предконнект и синтез) не открывается; без флага поведение прежнее; pytest **1244 passed**, ruff = база |
| S2 action_run | `sakura_core/proto_actions.py` (в `_load_portions`): `action_run` → `action_started`, ошибки bad_request/not_found/not_master; тот же Executor, confirm и power_confirm (вопрос — reply kind=confirm, ответ — voice_command «да»/«нет»); без `device` — активный ПК; «да» с телефона исполняется на ПК, о котором спрашивали; pytest **1262 passed**, ruff = база |
| S5 active и track | в `devices` и `device_update` добавлены `active: bool` и `track: {title, artist, status, cover_url\|null, ts}\|null` (из `state.device_tracks`, правило 60 с); device_update при смене трека/статуса (ws_protocol.update_current_track) и активного устройства (оба устройства); поля только добавлены; pytest **1267 passed**, ruff = база |
