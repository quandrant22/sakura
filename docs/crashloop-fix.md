# Устранение крашлупа после 12751a8 — 2026-09-17

## Четыре части

- `/opt/sakura/sakura_core/proactive.py:38`: функции заметок импортируются из `modules.autonomous`.
- `/opt/sakura/main.py:10`: `supervised` логирует полный traceback, не пробрасывает Exception; CancelledError сохраняется. Пять фоновых циклов обёрнуты; polling и WebSocket критичны. Автоперезапуск фонового цикла не добавлен.
- `/opt/sakura/tests/test_module_refs.py:71`: AST всех Python-файлов проекта, уникальный обход вложенных функций, разрешение ImportFrom/алиасов/относительных импортов/подмодулей, сводка всех ошибок. Не запускает тела циклов.
- `/opt/sakura/sakura_core/bridge.py:54`: одна проверенная коллекция деклараций для Router и Executor. Раньше bridge импортировал load(), затем Router вызывал load(), позже Executor мог вызвать третий раз. Общий load() не кэширован: явные загрузки тестовых YAML должны продолжать валидироваться.

## Проверки (дословно)

```
ruff check --select F821,B023 .
All checks passed!

pytest tests/ -q
436 passed, 2 warnings in 18.42s

Lazy imports: checked=724, failures=[]
Separate desktop applications (not runtime-checked on linux): 60 imports
```

Ограничение части 3: AST просмотрен для всех файлов, но runtime-разрешение 60 импортов Windows-агента, desktop-экспериментов и импорта `core` в тесте агентного окружения на Linux не выполнено. Моками они не подменены. Поэтому это не заявление о проверке всех платформ. Проверка ImportFrom также не покрывает произвольные обращения `module.attribute` и динамические строки import.

Сканер нашёл 13 настоящих битых ссылок после исправления proactive, а не ожидаемое «только одна». Исправления перечислены ниже.

## Живой эксперимент

Временный `/tmp/sakura-supervision-probe.py` подменил proactive_loop на RuntimeError до main.main(). Использовался runtime override `/run/systemd/system/sakura.service.d/90-supervision-probe.conf`, не исходники. Через существующий авторизованный Telethon-клиент отправлен `/health` боту и получен настоящий ответ. PID 1844141 остался прежним, NRestarts=0, агент pc подключился. Фрагмент журнала:

```
ERROR:main:[proactive_loop] упал
Traceback (most recent call last):
  File "/opt/sakura/main.py", line 16, in supervised
    await coro
  File "/tmp/sakura-supervision-probe.py", line 12, in broken_loop
    raise RuntimeError("SAKURA_SUPERVISION_PROBE: intentional background failure")
RuntimeError: SAKURA_SUPERVISION_PROBE: intentional background failure
INFO:aiogram.dispatcher:Run polling for bot @aisakura_bot id=8652776997 - 'Sakura'
INFO:sakura.probe:LIVE_TELEGRAM_OK: /health answered after background failure; response=Сервер: | CPU: 30%  |  load: 1.78 1.83 1.91 | RAM: 49% (3903 / 7941 МБ) | Диск: 45% (свободно 62 ГБ) | Аптайм: 0ч 0м
```

Override удалён, daemon-reload и systemctl restart sakura выполнены. Обычный main.py, PID 1844907, ActiveState=active, NRestarts=0. Реестр в новом процессе ровно один раз, Start polling/Run polling, нет Traceback/Polling stopped. Сырые 40 строк journalctl сохранены на VPS в /tmp/sakura-restored-journal.log (не публикуются в git: содержат идентификаторы пользователей и сессий).

Не скрытые проблемы: остановка предыдущего процесса превысила существующий TimeoutStopSec=5 (systemd применил SIGKILL); запрос погоды получил TLS timeout. Новый процесс продолжает работать. Эти проблемы не исправлялись.

## Сверх исходных четырёх правок: файл:строка — что и почему

- `/opt/sakura/adapters/commands.py:57` — device_manager вместо несуществующего modules.device: найдено AST-гвардией.
- `/opt/sakura/adapters/commands.py:62` — memory.db.get_memory_context вместо отсутствующего реэкспорта: найдено гвардией.
- `/opt/sakura/adapters/commands.py:74` — очистка истории из memory.memory вместо session: найдено гвардией.
- `/opt/sakura/adapters/commands.py:87` — сводки гостей из modules.users: найдено гвардией.
- `/opt/sakura/adapters/commands.py:92,112` — отсутствующий _find_user_by_username удалён из импортов; запрос username честно отклоняется, числовой ID передаётся вместе с обязательным name в add_vip/add_trusted. Нового механизма поиска пользователей не добавлено.
- `/opt/sakura/modules/discord_bot.py:217` — существующий _split_speech вместо отсутствующего split_into_chunks: найдено гвардией.
- `/opt/sakura/sakura_core/llm.py:306,648` — история/запись гостей из modules.users: найдено гвардией.
- `/opt/sakura/sakura_core/llm.py:546,568,607` — get_current_emotion из state_arbiter: найдено гвардией.
- `/opt/sakura/tests/test_registry.py:39` — явная загрузка обработчиков fixture, чтобы одиночный запуск не зависел от порядка импорта других тестов.

Файлы memory/mood_vector.json, memory/patterns.json, memory/rituals.json изменяются работающим сервисом и не включены в коммит.
