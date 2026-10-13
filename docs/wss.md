# wss:// для Сакуры — задача на переключение (без деплоя)

Цель: клиенты подключаются по `wss://<домен>/`, сам WebSocket Сакуры слушает
только `127.0.0.1:8765`, внешний порт 8765 закрыт. Домен владелец назовёт
позже — ниже он `SAKURA_DOMAIN`.

## Почему не «Caddy на 443»

Порт 443 на VPS занят nginx в режиме `stream` (`/etc/nginx/stream-vpn.conf`):
он по SNI (`ssl_preread`) разводит VPN, подписки и `default` на внутренние
порты. Caddy, занявший 443, сломал бы VPN. Поэтому:

```
клиент ──wss://SAKURA_DOMAIN:443──► nginx stream (SNI) ──► Caddy 127.0.0.1:8445 (TLS, Let's Encrypt)
                                                              └─► ws_handler 127.0.0.1:8765
```

- в `map` nginx добавляется одна строка `SAKURA_DOMAIN → 127.0.0.1:8445`,
  остальное в nginx не меняется; `reload` у nginx мягкий — открытые VPN-сессии
  дорабатывают на старых воркерах;
- Caddy слушает только localhost; сертификат получает через **TLS-ALPN-01**:
  проверка Let's Encrypt приходит на 443 с SNI домена и уходит к Caddy как
  есть; порт 80 не нужен (HTTP-проверка выключена);
- проксируются все пути: клиенты, как и сейчас, подключаются к корню.

Файлы в репозитории:

| файл | куда |
|---|---|
| `deploy/caddy/Caddyfile` | `/etc/caddy/Caddyfile` (заменить `SAKURA_DOMAIN`) |
| `deploy/nginx/stream-vpn.sakura.diff` | одна строка в `map` `/etc/nginx/stream-vpn.conf` |
| `deploy/systemd/sakura.service.d/wss.conf` | `/etc/systemd/system/sakura.service.d/wss.conf` |
| `scripts/wss_check.py` | проверка с любой машины |

## Шаги

0. **Заранее**: хеш отката кода — текущий прод; бэкапы
   `cp /etc/nginx/stream-vpn.conf /etc/nginx/stream-vpn.conf.bak-wss`.
1. **DNS**: A-запись `SAKURA_DOMAIN → 31.76.80.5`. Дождаться: `dig +short SAKURA_DOMAIN`.
2. **Caddy**: `apt install caddy` (Ubuntu 24.04: 2.6.2 — подходит; стенд
   проверен на 2.8.4). Пакет сразу стартует с примером на `:80` —
   `systemctl stop caddy`, затем
   `cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile`, заменить `SAKURA_DOMAIN`,
   `mkdir -p /var/log/caddy && chown caddy: /var/log/caddy`,
   `caddy validate --config /etc/caddy/Caddyfile`.
3. **nginx**: добавить строку из `stream-vpn.sakura.diff` в `map`,
   `nginx -t && systemctl reload nginx`.
4. **Сертификат**: `systemctl start caddy`; в `journalctl -u caddy -f`
   ждать `certificate obtained successfully` для `SAKURA_DOMAIN`.
5. **Проверка до переключения клиентов** (старый `ws://` ещё работает):
   `WS_SECRET=… python scripts/wss_check.py wss://SAKURA_DOMAIN/` —
   ждём «TLS 1.3, издатель Let's Encrypt», `registered proto=2`.
6. **Клиенты**: `VPS_WS_URL=wss://SAKURA_DOMAIN/` — в `agent\.env` и в
   настройках настольного клиента; перезапуск клиентов, проверка голосом.
7. **Закрыть 8765**: drop-in `wss.conf` → `systemctl daemon-reload &&
   systemctl restart sakura`; проверить, что в `/opt/sakura/.env` нет
   `WS_HOST` с другим значением; `ss -ltn | grep 8765` → `127.0.0.1:8765`.
   `ufw delete allow 8765/tcp`.
8. **Итоговая проверка**: `python scripts/wss_check.py wss://SAKURA_DOMAIN/
   --closed 31.76.80.5:8765` (с внешней машины): wss работает, 8765 закрыт;
   в журнале Сакуры нет новых `ОТКЛОНЕНО`.

После шага 8 можно выкатывать порцию 1 протокола v2 (журнал чата).

## Откат (в обратном порядке, каждый шаг независим)

| что | как |
|---|---|
| 8765 снова снаружи | `rm /etc/systemd/system/sakura.service.d/wss.conf && systemctl daemon-reload && systemctl restart sakura`; `ufw allow 8765/tcp` |
| клиенты | `VPS_WS_URL=ws://31.76.80.5:8765` |
| nginx | `cp /etc/nginx/stream-vpn.conf.bak-wss /etc/nginx/stream-vpn.conf && nginx -t && systemctl reload nginx` |
| Caddy | `systemctl disable --now caddy` (по желанию `apt remove caddy`) |

Пока не выполнен шаг 7, откат — просто вернуть клиентам `ws://`.

## Риски

- **Tailscale**: если какой-то клиент ходит на 8765 по адресу tailnet, после
  шага 7 он отвалится — перевести его на wss:// или оставить WS_HOST на
  интерфейсе tailscale.
- Порт `8766` («WebSocket himaryi client» в ufw) задача не трогает.
- Если домен попадёт в `default` (опечатка в `map`), TLS уйдёт в цепочку VPN
  и Caddy сертификат не получит — шаг 4 это покажет.
- `skip_install_trust` обязателен: без него Caddy, запущенный от root, при
  `tls internal` ставит свой корень в системное доверие (на стенде так и
  было — см. ниже).

## Стенд (проверено 2026-10-13 на этой машине, боевое не тронуто)

Тот же путь на высоких портах: тестовый nginx (тот же `stream` + `ssl_preread`
+ `map`) на `127.0.0.1:18443`, Caddy 2.8.4 с `tls internal` на
`127.0.0.1:18445`, настоящий `ws_handler` (ветка feat/proto-v2-devices) на
`127.0.0.1:18765`.

| проверка | результат |
|---|---|
| `wss://sakura.test:18443` с корнем стенда | TLS 1.3, `registered proto=2 master=True`, `devices`, `status`; ping 0,3–0,5 мс |
| чужой SNI | соединение сброшено (до Caddy не доходит) |
| клиент без корня стенда | `CERTIFICATE_VERIFY_FAILED` |
| `ws://` без TLS на 443-порт стенда | отказ |
| кадр 1,87 МБ (`vision_request`) через цепочку | дошёл, ответ сервера получен |

Замечание стенда: первый запуск Caddy без `skip_install_trust` поставил
корень «Caddy Local Authority» в `/usr/local/share/ca-certificates` и
системный бандл. Удалено (`caddy untrust`, две висячие ссылки в
`/etc/ssl/certs`); бандл проверен — следов нет. В боевой Caddyfile опция
добавлена.
