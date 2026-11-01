# Зрение: протокол клиента

Кадр экрана клиент снимает **только** по запросу сервера (или по явному действию пользователя — `window_ask`).
Сам по себе, по таймеру, клиент экран не снимает и не шлёт.

## Объявление поддержки

В `register` (proto 2):
```json
{"type": "register", "device_id": "...", "proto": 2, "features": ["vision.capture"], ...}
```

## Запрос и ответ

Сервер → клиент:
```json
{"type": "vision.capture", "request_id": "vc-…", "purpose": "ask|glance|watch",
 "max_side": 1280, "quality": 70, "need_change": false}
```

Клиент → сервер, ровно один ответ в течение 3 с (сервер ждёт 5 с):
```json
{"type": "vision.frame", "request_id": "vc-…", "device_id": "...", "status": "ok",
 "image": "<JPEG base64, ≤ 2 000 000 символов>",
 "window": {"title": "заголовок окна", "process": "code.exe"}, "changed": true}
```
```json
{"type": "vision.frame", "request_id": "vc-…", "device_id": "...", "status": "skipped",
 "reason": "private_window|unchanged|disabled|capture_failed|no_display"}
```

## Правила клиента

1. **Приватное окно — до снятия.** Если на переднем плане менеджер паролей, банк, окно инкогнито или окно из
   пользовательского списка — `skipped/private_window`, экран не снимается вовсе.
2. **`need_change: true`** — сравнить отпечаток экрана (64×36 RGB) с прошлым для этого `purpose`; не изменился
   (сумма разниц ≤ 64·36·6 и < 24 пикселей с разницей > 24) — `skipped/unchanged`, JPEG не кодируется.
3. **Выключатель** «Разрешить Сакуре поглядывать» выключен — на любой `purpose` кроме `ask` ответ `skipped/disabled`.
4. **Индикатор** на оверлее на время снятия кадра для `glance` и `watch`.
5. Кадр не пишется на диск и в лог; в лог — `purpose`, размер, `status/reason`.
