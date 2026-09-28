# Sakura VPS

## Установка

1. Создайте и активируйте виртуальное окружение Python 3.12.
2. Установите серверные зависимости:

   ```bash
   pip install -r requirements.txt
   ```

3. Создайте `.env` на основе `.env.example` и заполните Telegram, Gemini и WS-секреты.
4. Для Caddy задайте `WS_HOST=127.0.0.1`; по умолчанию сервер слушает `0.0.0.0`.
5. Запустите сервер: `python main.py`.

## Тесты

```bash
python -m pytest tests/ -q
python -m pytest agent/tests/ -q
```

## Архитектура

Обработчики Telegram, голоса и WebSocket используют общий реестр capabilities. VPS исполняет серверные действия, агент — команды устройства и браузерного расширения. История миграции и старые планы сохранены в `docs/`.
