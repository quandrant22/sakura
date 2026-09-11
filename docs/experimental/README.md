# Экспериментальное: ядро агента на Rust

## Что это

`core-rust/` — заготовка ядра агента на Rust (1244 строки: audio, vad, stt,
commands, protocol, ipc) и `launch.py` — лаунчер, который собирал и запускал
его как дочерний процесс через stdin/stdout JSON.

## Почему не подключено

Ни один путь выполнения агента это ядро не использует: реальная точка входа —
`agent/sakura.py`, распознавание речи и wake-word полностью живут в
`agent/core/hearing.py` на Vosk + Silero VAD. Документация, сборка и фактический
запуск расходились (README рекомендовал `launch.py`, BUILD/build.bat собирали
`sakura.py`), поэтому ядро убрано с дороги сюда, 2026-09.

## Что нужно для подключения

1. IPC-мост из `agent/core/hearing.py` в `core-rust/src/ipc` (stdin/stdout JSON
   по протоколу `core-rust/src/protocol`).
2. Лаунчер: `docs/experimental/launch.py` — собирал ядро (`cargo build --release`)
   и поднимал его процессом-соседом; при возврате учесть, что реальный агент
   теперь поднимает `sakura.py` (QApplication + tray), а не этот лаунчер.
3. Сверить команды: TOML-реестр `agent/commands/` — фактический источник;
   command-matching ядра (`core-rust/src/commands`) дублирует часть слотов.

Пока этого нет — ядро не собирать и не запускать: на VAD/STT оно не заменяет
ничего из работающего.

## Сюда же перенесены

- `bridge.py` — Python-сторона IPC-моста к ядру (`RustCore`, `Event`, `Action`);
  никем не импортируется, пути `core-rust/target/release/` внутри — устаревшие.
- `test_integration.py` — интеграционный тест ядра (`from core.bridge import …`);
  после переноса старые import-пути не действуют, это артефакты истории.
