# Протокол Sakura desktop

Два канала:

1. **Сервер ↔ ядро** — существующий WebSocket к VPS (`VPS_WS_URL`), расширенный
   версией 2. Реализован мок: `desktop/tools/mock_server.py`.
2. **Ядро ↔ интерфейс** — локальный WebSocket ядра на `127.0.0.1` для Electron-UI
   и PyQt6-оверлея.

Все сообщения — JSON-объекты с полем `type`. Время — Unix-секунды (float).

---

## 1. Сервер ↔ ядро

### 1.1 Уже существующие сообщения (протокол v1, не меняются)

| Направление | type | Поля |
|---|---|---|
| ядро → сервер | `register` | `device_id`, `token`, `active_window`, `system_info`, `focus_seconds`, `activity_level`, **новое:** `proto: 2` |
| ядро → сервер | `ping` | как `register` (heartbeat: при смене окна и не реже раза в 10 с); `system_info` — CPU, RAM, GPU, температуры, батарея; **новое (необяз.):** `input_idle_s` — секунд с последнего ввода мыши/клавиатуры (GetLastInputInfo), и в `register` тоже |
| ядро → сервер | `voice_command` | `device_id`, `token`, `text`, `active_window`, `context`; **новое (необяз.):** `channel: voice\|text` |
| ядро → сервер | `apps_list` | `device_id`, `token`, `apps` — только master-устройства |
| ядро → сервер | `command_result` | `id`, `device_id`, `token`, `ok`, `detail`, … |
| ядро → сервер | `screen_context`, `kettle_ready` | как сейчас |
| ядро → сервер | `bye` | **новое (необяз.):** `device_id`, `reason: shutdown\|sleep\|exit` — перед выключением/перезагрузкой, сном и выходом, не дольше 1 с; ответа нет (сервер §10.5) |
| сервер → ядро | `command` | `id`, `action`, `arg` — выполнить действие из реестра; `confirmed: true` — сервер уже спросил Мастера, клиент не переспрашивает |
| сервер → ядро | `reply` | `text`; необяз. `kind` (`llm`, `ack`, `template`, `error`, `proactive`, `confirm` — вопрос «Да или нет?»), `turn_id`, `ts` |
| сервер → ядро | `tts_chunk` / бинарные кадры / `tts_end` | озвучка (24 кГц, 16 бит) |
| сервер → ядро | `presence` | proto 2 (сервер §10.4): `event: arrival\|departure`, `from`, `to` — Сакура перешла между ПК |
| сервер → ядро | `mood_update` | proto 1: разбираются только `params.is_arrival` / `params.is_departure` (параметры настроения сервер больше не шлёт) |

Закрытие с кодом **4401** — авторизация не прошла или действие запрещено для
устройства (например, `apps_list` с не-master устройства).

Полный список запросов клиента — `desktop/core/protocol.py` (`CLIENT_REQUESTS`); сверка с кодом клиента
и с `V2_REQUESTS` сервера — `desktop/tests/test_protocol_contract.py`.

### 1.2 Регистрация v2

Ядро добавляет в `register` поле `proto: 2`. Сервер с поддержкой v2 отвечает:

```json
{"type": "registered", "device_id": "mostech", "proto": 2, "master": true}
```

Если ответа `registered` нет или `proto < 2` — ядро считает сервер «v1» и на
запросы v2 сразу отвечает интерфейсу ошибкой `unsupported` (без отправки на сервер).

### 1.3 Запросы v2 (только master-устройства)

Каждый запрос несёт `request_id` (строка, уникальна в соединении); ответ
повторяет его. Ядро ждёт ответ **10 с**, затем отдаёт интерфейсу ошибку
`timeout`. Пуш-сообщения сервера `request_id` не имеют.

| Запрос | Поля | Ответ |
|---|---|---|
| `history_request` | `limit` (по умолч. 50), `before_ts` (необяз.) | `history {messages:[Message]}` — по возрастанию `ts`, последние `limit` до `before_ts` |
| `chat_search` | `q`, `limit` | `chat_search {q, messages:[Message]}` |
| `chat_delete` | `id` | `chat_delete {id}` |
| `secure_devices` | — | `secure_devices {devices:[{device_id, name, fingerprint, paired_at, last_seen, online, secure_now, revoked, current}]}` — только по защищённому каналу (сервер §10.3) |
| `devices_request` | — | `devices {devices:[Device]}` |
| `status_request` | — | `status {tone, mode, context, quote}` |
| `scenarios_list` | — | `scenarios {scenarios:[Scenario]}` |
| `scenario_get` | `id` | `scenario {scenario}` |
| `scenario_save` | `scenario` (без `id` — создать) | `scenario {scenario}` |
| `scenario_delete` | `id` | `scenarios {scenarios}` |
| `scenario_run` | `id`, `confirm` (необяз.) | `scenario_run_started {run_id, id}`, затем пуши `scenario_event`; опасные шаги без `confirm: true` — ошибка `confirm_required` (окно спрашивает «Разрешить?» и повторяет с `confirm: true`) |
| `scenario_from_text` | `text` | `scenario_preview {scenario, warnings:[str]}` — не сохраняется |
| `memory_list` | `category` (необяз.), `offset`, `limit` | `memory_items {items, total, counts}` |
| `memory_search` | `q`, `limit` | `memory_items` |
| `memory_update` | `id`, `text` | `memory_items {items:[изменённая]}` |
| `memory_delete` | `id` | `memory_items {items:[]}` |
| `profile_get` | — | `profile {profile}` |
| `profile_set` | любые из `name, address_as, quiet_hours, voice, tone, notifications` | `profile {profile}` |

### 1.4 Пуши сервера

| type | Поля | Когда |
|---|---|---|
| `chat_message` | `message: Message` | каждое новое сообщение, включая голосовые (расшифровка) и ответы |
| `device_update` | `device: Device` | изменилось состояние устройства |
| `status` | `tone, mode, context, quote` | изменился статус |
| `scenario_event` | `run_id, step, status: ok\|error\|done, detail` | ход запуска сценария |

### 1.5 Типы

```jsonc
// Message
{"id": "m2", "ts": 1760090002.5, "role": "user|assistant|system",
 "text": "Сегодня у тебя:\n1. Созвон в 11:00", "channel": "voice|text|telegram", "device": "mostech"}

// Device
{"id": "phone", "name": "Телефон", "kind": "pc|phone|tablet|headphones|other",
 "online": true, "last_seen": 1760090290.0, "focus": false,
 "stats": {"cpu": null, "ram": null, "gpu": null, "battery": 78, "charging": false,
           "wifi": "Home", "signal": 3}}

// Scenario
{"id": "sleep", "name": "Режим сна", "enabled": true, "builtin": false,
 "conditions": [{"type": "phrase|time|device_connected|device_disconnected|app_started", "value": "22:00-07:00"}],
 "actions":    [{"type": "action|pause|telegram|notify", "value": "phone.dnd_on"}]}

// MemoryItem
{"id": "k1", "category": "preferences|facts|bookmarks|…", "text": "…", "ts": 1760000000.0}

// Profile
{"name": "…", "address_as": "ты", "quiet_hours": "23:00-07:00", "voice": "Leda",
 "tone": "calm", "notifications": {"telegram": true, "sound": true}}
```

### 1.6 Ошибки

```json
{"type": "error", "request_id": "r1", "code": "not_found", "message": "сценарий не найден"}
```

| code | Значение |
|---|---|
| `bad_request` | нет обязательного поля или неверное значение |
| `not_found` | объект с таким `id` не найден |
| `unauthorized` | неверный токен |
| `not_master` | запрос v2 с не-master устройства |
| `unsupported` | сервер не поддерживает proto 2 / этот запрос |
| `unknown_type` | (мок-сервер) запроса нет в V2_REQUESTS сервера |
| `confirm_required` | `scenario_run` с опасными действиями без `confirm: true` |
| `secure_channel_required` | приватный запрос (`chat_*`, `memory_*`, `profile_*`, `secure_devices`) не по защищённому каналу |
| `timeout` | (выставляет ядро) ответа нет за 10 с |
| `offline` | (выставляет ядро) нет соединения с сервером |

### 1.7 Пример сессии

```
→ {"type":"register","device_id":"mostech","token":"…","proto":2, …}
← {"type":"registered","device_id":"mostech","proto":2,"master":true}
→ {"type":"history_request","request_id":"h1","limit":50}
← {"type":"history","request_id":"h1","messages":[…]}
→ {"type":"voice_command","text":"Включи музыку","channel":"text", …}
← {"type":"chat_message","message":{"role":"user","text":"Включи музыку", …}}
← {"type":"command","id":"c7","action":"music.wave","arg":""}
→ {"type":"command_result","id":"c7","ok":true, …}
← {"type":"reply","text":"Включаю «Мою волну»."}
← {"type":"chat_message","message":{"role":"assistant", …}}
```

---

## 2. Ядро ↔ интерфейс (локальный API)

### 2.1 Подключение

- WebSocket только на `127.0.0.1:<порт>`; порт и токен ядро пишет в
  `%LOCALAPPDATA%\Sakura\ui.token` (JSON `{"port": 8790, "token": "…"}`,
  права только текущего пользователя; новый токен на каждый запуск ядра).
- Клиент первым сообщением шлёт `{"type":"hello","token":"…","client":"ui|overlay"}`.
  Неверный токен или нет `hello` за 5 с — закрытие с кодом **4401**.
- Заголовок `Origin` должен быть из белого списка: `file://` (Electron, сборка),
  `http://localhost:5173` (dev), без `Origin` (оверлей на Python). Иначе — **4403**.
- В ответ на `hello` ядро шлёт снимок: `connection`, `state`, `settings`, `devices`
  (если есть в кэше).

### 2.2 События (ядро → интерфейс)

| type | Поля |
|---|---|
| `state` | `value: idle\|listening\|thinking\|speaking`, `level` (0..1, уровень звука) |
| `transcript` | `text`, `final: bool` — промежуточная/финальная расшифровка |
| `chat_message` | `message: Message` |
| `devices` / `device_update` | как у сервера |
| `status` | `tone, mode, context, quote` |
| `scenarios`, `scenario`, `scenario_preview`, `scenario_event`, `scenario_run_started` | как у сервера |
| `memory_items` | как у сервера (не логируется) |
| `profile` | как у сервера |
| `notify` | `text`, `level: info\|warn\|error` |
| `settings` | `settings: {...}` — текущие локальные настройки ядра |
| `log` | `level`, `text` (для диагностической страницы) |
| `connection` | `server: online\|offline`, `proto: 1\|2` |
| `reply` | ответ на команду интерфейса: `request_id`, `ok`, `result` или `error {code, message}` |

### 2.3 Команды (интерфейс → ядро)

Все несут `request_id`; ядро отвечает `reply` с тем же `request_id`.

| type | Поля | Результат |
|---|---|---|
| `send_text` | `text` | отправка `voice_command` с `channel: text` |
| `mic_toggle` | `on` (необяз.) | `{mic: bool}` |
| `stop_speaking` | — | остановка озвучки (как «стоп») |
| `listen_now` | — | «говорить сейчас» без слова «Сакура»: прерывает озвучку, открывает окно дослушивания; `mic_off`, если микрофон выключен |
| `quick_action` | `id: screenshot\|open_app\|focus_mode\|run_scenario`, `arg` | результат действия |
| `list_apps` | — | `{apps: [{name}]}` |
| `list_audio_devices` | — | `{inputs: [...], outputs: [...]}` |
| `settings_set` | `key`, `value` | новые `settings` |
| `server` | `message: {type: history_request\|…}` | проброс запроса v2 серверу; ответ сервера приходит в `result`; ошибки `timeout`, `offline`, `unsupported` |

### 2.4 Пример

```
→ {"type":"hello","token":"…","client":"ui"}
← {"type":"connection","server":"online","proto":2}
← {"type":"state","value":"idle","level":0}
→ {"type":"server","request_id":"u1","message":{"type":"history_request","limit":50}}
← {"type":"reply","request_id":"u1","ok":true,"result":{"type":"history","messages":[…]}}
→ {"type":"send_text","request_id":"u2","text":"Погода"}
← {"type":"reply","request_id":"u2","ok":true}
← {"type":"chat_message","message":{…}}
```

## command_result: статус выполнения (клиент, 2026-10-12)

`command_result` агента содержит `ok`, `status` и `detail`:

| status | ok | смысл | что говорить |
|---|---|---|---|
| `done` | true | действие выполнено | «Готово» / результат |
| `noop` | false | делать нечего (нет активного плеера, уже так) | «Не получилось: <detail>» |
| `failed` | false | пытались, не вышло | «Не получилось: <detail>» |
| `unsupported` | false | нет исполнителя или условия (расширение, токен, сопряжение) | «Не получилось: <detail>» |

ok=true только при status=done. Серверный агент меняет ответы отдельно; клиент шлёт поля уже сейчас.
