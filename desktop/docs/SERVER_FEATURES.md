# Возможности, зависящие от сервера (20.10.2026)

Сверено с исходниками сервера: ветка `origin/server/presence-memory` (`sakura_core/proto_v2.py`,
`proto_chat.py`, `proto_devices.py`, `proto_scenarios.py`, `proto_memory.py`, `proto_profile.py`,
`adapters/ws.py`, `docs/security/PROTOCOL.md` §10) и `origin/server/power` (§10.7, `power_confirm.py`).
Список запросов клиента — `desktop/core/protocol.py` (`CLIENT_REQUESTS`); тест
`desktop/tests/test_protocol_contract.py` проверяет, что клиент шлёт только их и что каждый есть в `V2_REQUESTS`.

## Как окно показывает ответы сервера

`store.ts`: `errorKind`, `errorText`.

| Вид | Коды ответа | Текст для пользователя |
|---|---|---|
| ещё не поддерживает | `unsupported`, `unknown_type`, `unknown_command`, сервер v1 | «Сервер ещё не поддерживает» |
| нужен защищённый канал | `secure_channel_required` | «Нужен защищённый канал: включи VPN или подключи устройство (Настройки → Безопасность)» |
| нужно подтверждение | `confirm_required` (только `scenario_run`) | окно «Разрешить?» с текстом сервера; «Да» — повтор с `confirm: true`, «Нет» — ничего |
| не отвечает | `timeout` | «Сервер не отвечает» |
| нет связи | `offline`, `core_offline` | «Нет связи с сервером» / «с ядром» |
| ошибка | всё остальное | текст сервера (`not_found` — «сообщение не найдено» и т.п.) |

Настоящий сервер на запрос из `V2_REQUESTS` без обработчика отвечает `unsupported`; на тип вне списка не
отвечает вовсе (клиент через 10 с получает `timeout`). Мок-сервер отвечает `unknown_type`.

Приватные классы (`chat_*`, `history_*`, `memory_*`, `profile_*`, `secure_*`, `vision_request`) сервер отдаёт только
по защищённому каналу (Noise или локальный источник, PROTOCOL.md сервера §5.1). `secure_devices` — только по
защищённому каналу всегда, независимо от `PRIVATE_REQUIRES_SECURE`.

## Запросы (клиент → сервер, `request_id`)

| Экран / функция | Запрос | Сервер | Мок | Состояние в окне |
|---|---|---|---|---|
| Чат: история | `history_request` {limit, before_ts} → `history` {messages, has_more} | да | да | готово, «Загрузить раньше» |
| Чат: поиск | `chat_search` {q, limit} → `chat_search` {q, messages} | да | да | готово |
| Чат: удалить сообщение | `chat_delete` {id} → `chat_delete` {id} | да | да | «Удалить?» в окне, затем запрос |
| Чат: экспорт | — (локально) | — | — | готово |
| Устройства | `devices_request` → `devices` {devices}; пуш `device_update` | да | да | готово; активное — `focus` |
| Статус | `status_request` → `status` | да | да | готово |
| Сценарии: список, удалить, из фразы | `scenarios_list`, `scenario_delete`, `scenario_from_text` | да | да | готово |
| Сценарии: запуск | `scenario_run` {id, confirm?} → `scenario_run_started`, пуши `scenario_event` | да; опасные шаги — `confirm_required` | да | «Разрешить?» и повтор с `confirm: true` |
| Память | `memory_list/search/update/delete` | да | да | готово |
| Профиль | `profile_get/set` | да | да | готово |
| Безопасность → Устройства | `secure_devices` → {device_id, name, fingerprint, paired_at, last_seen, online, secure_now, revoked, current} | да (только защищённый канал) | да | список, текущее отмечено; `unknown_type`/`unsupported` — «Сервер ещё не поддерживает» |
| Спросить про окно | `vision_request` (вне диспетчера v2, `adapters/ws.py`) | да | нет | без защищённого канала — подсказка |

Есть в `V2_REQUESTS`, клиент пока не шлёт: `chat_send` (текст идёт `voice_command` с `channel: text`),
`chat_read`, `chat_clear`, `scenario_get`, `scenario_save`.

## Сообщения без ответа (клиент → сервер)

| Сообщение | Поля | Сервер |
|---|---|---|
| `register`, `ping` | + `input_idle_s` (секунд с последнего ввода; необяз.) | §10.1, §10.6: активное устройство и присутствие Мастера по вводу. Ping — при смене окна и не реже раза в 10 с |
| `bye` | `device_id`, `reason: shutdown\|sleep\|exit` | §10.5: ПК сразу офлайн с причиной; следующий `register`/`ping` снимает пометку. Клиент шлёт перед выключением, перезагрузкой, сном и выходом (не дольше 1 с) |

## Пуши и команды (сервер → клиент)

| Сообщение | Клиент |
|---|---|
| `presence` {event: arrival\|departure, from, to} (proto 2, §10.4) | строка «Сакура перешла на <имя ПК>» в уведомлениях окна; `orb_arrival`/`orb_departure` для оверлея |
| `mood_update` (proto 1) | только `is_arrival`/`is_departure`; общая рассылка настроения на сервере выключена (`MOOD_BROADCAST=off`) |
| `reply` с `kind: "confirm"` (server/power, §10.7) | вопрос «Выключить игровой компьютер? Да или нет?» в чате с кнопками «Да»/«Нет»; ответ уходит обычным текстом «да»/«нет» |
| `command` {action: system.shutdown\|system.restart\|power.sleep, confirmed: true} | исполняется сразу, без своего «Разрешить?», на любом ПК; перед этим `bye` с причиной; выключение и перезагрузка — `/t 0` |
| `context_transfer`, команда `abort_all` | сервер не шлёт — клиент их больше не разбирает |

## Нет на сервере

- Ничего из того, что шлёт клиент: все запросы `CLIENT_REQUESTS` есть в `V2_REQUESTS`.
- Подтверждение питания (`reply kind=confirm`, команды с `confirmed`) — в ветке `server/power`; без неё сервер
  спрашивает по-старому, клиент работает так же.
