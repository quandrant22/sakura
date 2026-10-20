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

