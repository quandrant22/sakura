"""core/file_index.py — собственный индекс файлов по всему диску.

Зачем свой, а не Everything: Everything требует админа и UAC на каждый запуск.
Зачем не Windows Search: он индексирует только включённые папки, скрытое и весь
диск туда не входят.

Решение: один раз обходим все диски в фоне (os.walk, без админа), кэшируем пути
на диск, поиск идёт по индексу в памяти — мгновенно, с фаззи-матчингом. Скрытые
папки os.walk видит сам (на Windows «скрытый» — атрибут, не имя), они в индексе.
Недоступное и системный мусор отсекаются исключениями и onerror.

Интерфейс:
    idx = FileIndex(); idx.start()        # фоновая сборка/обновление
    paths = idx.search("отчёт", limit=5)  # список путей по релевантности
    opened = idx.open("отчёт")            # открыть верхний результат, вернуть путь
"""

import os
import sys
import json
import time
import string
import logging
import tempfile
import threading
from difflib import SequenceMatcher

log = logging.getLogger("sakura.file_index")

_IS_WIN = sys.platform == "win32"

# Папки-исключения по имени (нижний регистр): чистый мусор и недоступное.
# Тюнингуется — можно добавить "windows", "appdata", "node_modules", если шумит.
_DEFAULT_EXCLUDES = {
    "$recycle.bin", "system volume information", "winsxs",
    "$windows.~ws", "$windows.~bt", "recovery",
}

# Расширения, которые при равном совпадении ценнее (то, что обычно «открывают»).
_PREFERRED_EXT = {
    ".exe", ".lnk", ".url", ".pdf", ".docx", ".xlsx", ".pptx", ".txt",
    ".jpg", ".png", ".mp3", ".mp4", ".zip", ".py", ".md",
}

_REFRESH_SEC = 6 * 3600          # фоновое переобновление индекса
_MAX_INDEX   = 2_000_000         # потолок записей — страховка от разрастания


class FileIndex:
    def __init__(self, cache_path: str = "file_index.json",
                 excludes: set[str] | None = None,
                 roots: list[str] | None = None):
        self._cache_path = cache_path
        self._excludes   = {e.lower() for e in (excludes or _DEFAULT_EXCLUDES)}
        self._roots      = roots                       # None → авто (диски / корень)
        self._entries: list[tuple[str, str]] = []      # (basename_lower, full_path)
        self._built_at   = 0.0
        self._lock       = threading.Lock()
        self._building   = False

    # ── корни обхода ────────────────────────────────────────────────
    def _scan_roots(self) -> list[str]:
        if self._roots:
            return self._roots
        if _IS_WIN:
            return [f"{d}:\\" for d in string.ascii_uppercase
                    if os.path.exists(f"{d}:\\")]
        return ["/"]                                   # для отладки вне Windows

    # ── построение индекса ──────────────────────────────────────────
    def _walk(self) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        for root in self._scan_roots():
            for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
                # отсекаем мусорные ветки на месте — не спускаемся внутрь
                dirnames[:] = [d for d in dirnames if d.lower() not in self._excludes]
                for name in filenames:
                    entries.append((name.lower(), os.path.join(dirpath, name)))
                    if len(entries) >= _MAX_INDEX:
                        return entries
        return entries

    def _build(self):
        if self._building:
            return
        self._building = True
        try:
            t0 = time.monotonic()
            entries = self._walk()
            with self._lock:
                self._entries = entries
                self._built_at = time.time()
            self._save_cache()
            log.info("индекс собран: %d файлов за %.1fс",
                     len(entries), time.monotonic() - t0)
        except Exception as e:
            log.error("сборка индекса упала: %s", e)
        finally:
            self._building = False

    # ── кэш ─────────────────────────────────────────────────────────
    def _save_cache(self):
        try:
            with self._lock:
                data = {"built": self._built_at,
                        "paths": [p for _, p in self._entries]}
            dir_ = os.path.dirname(self._cache_path) or "."
            with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False,
                                             encoding="utf-8", suffix=".tmp") as f:
                json.dump(data, f, ensure_ascii=False)
                tmp = f.name
            os.replace(tmp, self._cache_path)
        except Exception as e:
            log.error("кэш не сохранён: %s", e)

    def _load_cache(self) -> bool:
        if not os.path.exists(self._cache_path):
            return False
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            paths = data.get("paths", [])
            with self._lock:
                self._entries  = [(os.path.basename(p).lower(), p) for p in paths]
                self._built_at = data.get("built", 0.0)
            log.info("индекс из кэша: %d файлов", len(paths))
            return True
        except Exception as e:
            log.error("кэш не прочитан: %s", e)
            return False

    # ── фоновый запуск ──────────────────────────────────────────────
    def start(self):
        """Грузит кэш (поиск сразу доступен), потом в фоне собирает/обновляет."""
        self._load_cache()
        threading.Thread(target=self._refresh_loop, daemon=True).start()

    def _refresh_loop(self):
        # пустой или устаревший кэш — пересобрать сразу, иначе ждать цикла
        if not self._entries or (time.time() - self._built_at) > _REFRESH_SEC:
            self._build()
        while True:
            time.sleep(_REFRESH_SEC)
            self._build()

    def rebuild_now(self):
        """Принудительная пересборка в фоне (например, по голосовой команде)."""
        threading.Thread(target=self._build, daemon=True).start()

    # ── поиск ───────────────────────────────────────────────────────
    def _score(self, query: str, name: str, path: str) -> float:
        stem = name.rsplit(".", 1)[0] if "." in name else name
        ext  = os.path.splitext(name)[1]
        if name == query or stem == query:
            base = 1.0
        elif name.startswith(query) or stem.startswith(query):
            base = 0.9
        elif query in name:
            base = 0.75
        else:
            base = SequenceMatcher(None, query, name).ratio()
        if ext in _PREFERRED_EXT:
            base += 0.03
        base -= min(0.05, len(path) / 6000)            # лёгкое предпочтение коротким путям
        return base

    def search(self, query: str, limit: int = 5, min_score: float = 0.5) -> list[str]:
        q = query.strip().lower()
        if not q:
            return []
        with self._lock:
            entries = self._entries
        # дешёвый префильтр по вхождению, фаззи — только на выживших
        prefiltered = [(n, p) for n, p in entries if q in n]
        pool = prefiltered if prefiltered else entries
        scored = [(self._score(q, n, p), p) for n, p in pool]
        scored = [s for s in scored if s[0] >= min_score]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:limit]]

    def open(self, query: str) -> str | None:
        """Открывает верхний результат родной ассоциацией Windows. Возвращает путь."""
        hits = self.search(query, limit=1)
        if not hits:
            return None
        path = hits[0]
        try:
            os.startfile(path)                          # type: ignore[attr-defined]
            return path
        except Exception as e:
            log.error("не открылось %s: %s", path, e)
            return None

    @property
    def ready(self) -> bool:
        return bool(self._entries)

    @property
    def size(self) -> int:
        return len(self._entries)