"""Расписание вуза (МУИВ): разбор, хранение, изменения, напоминания.

Схема и решения — docs/SCHEDULE.md, строки R* в docs/DECISIONS.md.

  ttable (HTML) ── direct: fetch.py (VPS → ajax.php, только по белому списку вуза)
               └─ push:   push_server.py (букмарклет из браузера Мастера)
       │
  sync.ingest → parse → store.merge → diff → notify (proactive) / briefing
       │
  query: today / on(date) / week / current / next — для команд и контекста
"""
