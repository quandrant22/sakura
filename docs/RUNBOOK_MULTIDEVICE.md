# Выкатка server/multidevice (не выполнялась)

Ветка `server/multidevice` стоит поверх `server/integration`
(securechannel + proto-v2-rest + server-autonomy). Выкатывает владелец.

## Перед выкаткой

- Откат: запомнить `git rev-parse HEAD` в `/opt/sakura` (на 2026-10-20 прод = 2a9e6a3).
- В `.env` `mostech` должен быть в `MASTER_DEVICES` (на момент подготовки — да).
  `DEVICES` не задавать: по умолчанию `pc,laptop,mostech,phone`.
- Новый пакет: `pip install -r requirements.txt` в боевом venv (нужны
  `noiseprotocol`, `qrcode[pil]`, `cryptography`). Без него ветка не стартует
  защищённый канал.
- `SECURE_CHANNEL` оставить `off` — включение отдельным шагом (см. docs/security).
- Порция 1 (журнал чата) выкатывается при `PRIVATE_REQUIRES_SECURE=1` (по умолчанию):
  приватные классы по обычному ws:// не отдаются.

## Выкатка

1. `cd /opt/sakura && git fetch && git merge --ff-only origin/server/multidevice`
   (или влить ветку в master по обычному процессу).
2. `venv/bin/pip install -r requirements.txt`
3. `systemctl restart sakura`

## Проверка

1. В логе нет трейсбеков; `/devices` в Telegram работает.
2. Включить три ПК: активное не должно скакать
   (`grep "presence_sync" journal`: строки «активное → …» только при вводе).
3. Ввод/голос на другом ПК — «Фокус переехал» один раз.
4. Музыка на одном ПК: в промпт идёт этот трек, у другого ПК не смешивается.
5. Клиент proto 2: `secure_devices` по Noise — список; по обычному ws:// — отказ.
6. Старый клиент получает `mood_update` только с `is_arrival`/`is_departure`.

## Откат

`git checkout <сохранённый хэш>`, `systemctl restart sakura` (`git reset --hard` запрещён правилами проекта).
Состояние активного устройства и треков живёт в памяти процесса; файлов
данных ветка не меняет (devices.json лишь дополняется mostech).

## Что включается позже

- `MOOD_BROADCAST=on` вернёт общую рассылку настроения.
- Клиенты начнут слать `input_idle_s` — до этого работает прежняя логика.
