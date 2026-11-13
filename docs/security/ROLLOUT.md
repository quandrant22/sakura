# Выкат защищённого канала (SECURE_CHANNEL off → optional → required)

> **Статус 2026-11-10:** шаг 3 выполнен — `SECURE_CHANNEL=required`. Внешний транспорт —
> `wss://` (TLS 1.3) через nginx на :443, сервер слушает только `127.0.0.1:8765`
> (`WS_HOST`), адрес для клиентов — `SECURE_PUBLIC_URL` в `.env`. Спаривание XXpsk3 в
> `required` работает (`tests/test_securechannel_ws.py::test_required_still_allows_pairing_a_new_device`).
> Откат: `SECURE_CHANNEL=optional` и рестарт. Шаг 4 (вывод `WS_SECRET`) — через неделю без откатов.

Выполняет владелец на VPS. Ключи и реестр — [KEYS.md](KEYS.md), протокол —
[PROTOCOL.md](PROTOCOL.md). Секреты (`.env`, `memory/secure/`) в чат, лог и
git не попадают.

## Готовность клиентов (2026-11-03)

| клиент | где | Noise | спаривание | готов к `required` |
|---|---|---|---|---|
| desktop | ветка `feat/desktop-integrated` | да, interop с сервером 18/18 | да (QR / 8 слов, отпечаток) | да |
| Android | ветка `feat/mobile-android` | да, официальные векторы | да | да |
| agent | ветка `feat/agent-pairing` (ТЗ-4) | да, без отката на token | да: трей → «Спарить с сервером…» (QR-строка или 8 слов), ключ под DPAPI | да, после спаривания |
| agent | master до слияния `feat/agent-pairing` | транспорт есть | **нет хранилища ключей** — всегда token | **нет** |

Основной клиент на ПК — `desktop/` (DECISIONS U1): спаривается в окне «Подключение»
(QR-строка или 8 слов, отпечаток). `agent/` — запасной; если он запущен, его тоже
нужно спарить или закрыть. Пока на ПК работает агент без `feat/agent-pairing`,
дальше шага 2 (`optional`) не идти.

Обновление агента до спаривания: `pip install -r agent/requirements.txt`
(добавлены `noiseprotocol`, `cryptography`), при сборке .exe — свежий `build.bat`.

## Шаг 0. Подготовка

```sh
cd /opt/sakura
git rev-parse HEAD                      # записать в PROGRESS_SERVER.md как хэш отката
sudo systemctl status sakura --no-pager
venv/bin/pip install -r requirements.txt   # noiseprotocol, cryptography, qrcode
venv/bin/python -m pytest -q tests/test_securechannel_*.py
tar czf ~/backup/memory-$(date +%F).tgz memory/   # резервная копия, хранить зашифрованно
```

Проверить (только True/False, значения не печатать):
`PRIVATE_REQUIRES_SECURE` не выключен, `SECURE_PUBLIC_URL` — внешний адрес
сервера, клиенты в `MASTER_DEVICES`.

## Шаг 1. optional

В `.env`: `SECURE_CHANNEL=optional`, `systemctl restart sakura`.

Проверка:
- в журнале: создан `memory/secure/server_keys.json`, права `600`, каталог `700`
  (`stat -c '%a %n' memory/secure memory/secure/*`);
- старые клиенты по токену подключаются как раньше;
- приватные классы (чат v2, память, кадры экрана) по `ws://` — отказ
  «нужен защищённый канал» (это ожидаемо).

Откат: `SECURE_CHANNEL=off` и рестарт; ключи не удалять.

## Шаг 2. Спаривание

Для каждого устройства (агент или desktop на ПК, телефон):
1. Telegram: `/pair` → QR, 8 слов, отпечаток ключа сервера.
2. Клиент: **QR** (не слова — FORMAL §3.2: по словам остаётся окно
   офлайн-перебора PSK для активного посредника), сверить отпечаток.
   Агент: трей → «Спарить с сервером…» → вставить QR-строка `sakura-pair://…`
   (текст из QR или из сообщения /pair). Ключ сервера сверяется автоматически;
   при подмене спаривание обрывается до XX_3. Агент сам переподключится,
   в трее — «🔒 защищённый канал».
3. Сообщение «Спарено устройство …» → удалить сообщение с кодом.
4. В клиенте «Канал: защищён» (🔒), `/devices` показывает устройство.

Проверка на mostech по регламенту живых проверок: «глянь на экран» —
ответ есть (кадр шёл по Noise); в журнале сервера у соединения
`transport=noise`.

## Шаг 3. required

Только когда **все** используемые клиенты спарены и ни один старый
`agent/` не работает.

`SECURE_CHANNEL=required`, рестарт. Проверка:
- спаренные клиенты переподключились, 🔒;
- вход по токену → закрытие **4412** (проверить тестовым клиентом без ключей);
- неизвестный ключ → молчание и 4408 в дедлайн.

Откат (аварийно): `sudo scripts/secure_recovery.sh` (drop-in `off`, вход по
`WS_SECRET`; ключи и реестр не трогаются), обратно — `--undo`.

## Шаг 4. Вывод WS_SECRET

Через неделю на `required` без откатов: удалить `WS_SECRET` у клиентов,
на сервере сменить его на случайное значение (нужен только
`secure_recovery.sh`) и записать новое значение в менеджер паролей
владельца, не в репозиторий.

---

## ТЗ-4. agent/: хранилище ключа устройства и спаривание

**Статус:** выполнено в `feat/agent-pairing` (DECISIONS CV20–CV24). Живая
проверка на ПК — за владельцем (шаг 2).

**Контекст.** `agent/core/transport.py` (из `feat/agent-securechannel`)
умеет Noise IK и не откатывается на токен, но ищет модуль `core.secure_store`,
которого нет, — ключей устройства никогда нет, агент всегда входит по
`WS_TOKEN`. В тестах используется фейк `agent/tests/fake_secure_store.py`.
Эталон — `desktop/core/securechannel/{keys,pairing}.py` и мастер
«Подключение» в desktop. Ветка: `feat/agent-pairing` от `master`.

**Требуемый результат.**
1. `agent/core/secure_store.py` с API фейка (`load`, `save`,
   `set_next_server_pub`, `promote_next`, `wipe`; запись `DeviceKeys`): файл `%APPDATA%\Sakura\secure\device.json`,
   атомарная запись, ACL только текущему пользователю (на Windows — через
   `icacls /inheritance:r /grant:r %USERNAME%:F`, на прочих ОС — 600).
2. Спаривание `XXpsk3` через `securechannel.client` (тот же пакет, что у
   сервера): ввод QR-строки `sakura-pair://…` или 8 слов; показ отпечатка
   ключа сервера до отправки XX_3; при QR — сверка ключа из XX_2 с ключом
   из QR **до** XX_3 (PROTOCOL §3.3).
3. UI: пункт трея «Спарить с сервером…» (диалог ввода, отпечаток,
   результат), статус 🔒 в оверлее уже есть.
4. После спаривания — переподключение без перезапуска (`transport.wait_for_keys`).

**Архитектурные ограничения.**
- Своих криптопримитивов нет; только `securechannel` (lib-бэкенд).
- Ключи, PSK, слова, QR-строка не пишутся в лог и не показываются после ввода;
  в лог — отпечаток, `device_id`, код результата.
- Неудача спаривания не трогает прежние ключи.
- Протокол — строго PROTOCOL.md; новые поля только по согласованию.

**Ожидаемые артефакты.**
- Код, `agent/tests/test_secure_store.py` (атомарность, права/ACL с mock
  `icacls`, ротация `set_next_server_pub`→`promote_next`), `agent/tests/test_agent_pairing.py`
  против настоящего `securechannel.server` на 127.0.0.1: QR, слова, неверные
  слова, подмена ключа сервера при QR → обрыв до XX_3.
- `ruff`, `pytest` для `agent/`; строки в `docs/DECISIONS.md`.
- Живая проверка: спаривание агента на mostech по QR, `/devices`, 🔒.
