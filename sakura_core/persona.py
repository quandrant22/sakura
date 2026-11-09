"""sakura_core/persona.py — единое хранилище образа Сакуры.

Образ — это характер и манера речи: кто она, как говорит, чего не делает.
Он хранится в одном месте — каталоге PERSONA_DIR (по умолчанию
memory/persona/), по файлу на режим:

    master.md    — обычная Сакура с Мастером
    guest.md     — с гостями и в общем чате
    intimate.md  — режим 18+ (только с Мастером, только в его канале)

Если файла режима нет, читается заводской образ из persona/ в репозитории.
Перезаписывается образ только через set()/reset()/rollback(): атомарно,
с копией прежней версии в PERSONA_DIR/.history (последние HISTORY_KEEP).
Чтение кэшируется по mtime: правка файла подхватывается без перезапуска.

В образ НЕ входят правила, которые нельзя ослабить переписыванием:
честность памяти, границы режима 18+, приватность Мастера. Они живут в
personality.py и добавляются к образу при сборке промпта.

В журнал пишутся режим, размер и источник правки — не текст образа.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("sakura.persona")

MODES: tuple[str, ...] = ("master", "guest", "intimate")
MAX_CHARS = 12_000
MIN_CHARS = 40
HISTORY_KEEP = 10

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_DIR = _REPO_ROOT / "persona"

_lock = threading.Lock()
# path → (mtime_ns, size, text)
_cache: dict[str, tuple[int, int, str]] = {}


class PersonaError(ValueError):
    """Образ не прошёл проверку: режим, пустота, размер."""


def persona_dir() -> Path:
    """Каталог рабочего образа. PERSONA_DIR — для тестов и нестандартных установок."""
    return Path(os.environ.get("PERSONA_DIR") or (_REPO_ROOT / "memory" / "persona"))


def _check_mode(mode: str) -> str:
    if mode not in MODES:
        raise PersonaError(f"неизвестный режим образа: {mode!r}; есть: {', '.join(MODES)}")
    return mode


def _runtime_path(mode: str) -> Path:
    return persona_dir() / f"{mode}.md"


def _default_path(mode: str) -> Path:
    return DEFAULTS_DIR / f"{mode}.md"


def _read_cached(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("[persona] не прочитала %s: %s", path.name, type(e).__name__)
        return None
    with _lock:
        _cache[key] = (st.st_mtime_ns, st.st_size, text)
    return text


def _valid(text: str | None) -> bool:
    return bool(text) and MIN_CHARS <= len(text.strip()) <= MAX_CHARS


def origin(mode: str) -> str:
    """'custom' — действует рабочий файл, 'default' — заводской образ."""
    _check_mode(mode)
    return "custom" if _valid(_read_cached(_runtime_path(mode))) else "default"


def get(mode: str) -> str:
    """Текущий образ режима. Битый или пустой рабочий файл → заводской образ."""
    _check_mode(mode)
    text = _read_cached(_runtime_path(mode))
    if _valid(text):
        return text.strip()
    if text is not None:
        log.warning("[persona] рабочий образ %s не прошёл проверку — беру заводской", mode)
    default = _read_cached(_default_path(mode))
    if not _valid(default):
        raise PersonaError(f"нет заводского образа для режима {mode!r}")
    return default.strip()


def get_default(mode: str) -> str:
    _check_mode(mode)
    text = _read_cached(_default_path(mode))
    if not _valid(text):
        raise PersonaError(f"нет заводского образа для режима {mode!r}")
    return text.strip()


def version() -> str:
    """Короткий отпечаток всех действующих образов — для ключей кэша промпта."""
    h = hashlib.md5()
    for mode in MODES:
        for p in (_runtime_path(mode), _default_path(mode)):
            try:
                st = p.stat()
                h.update(f"{p}:{st.st_mtime_ns}:{st.st_size};".encode())
            except OSError:
                h.update(f"{p}:-;".encode())
    return h.hexdigest()[:12]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _history_dir() -> Path:
    return persona_dir() / ".history"


_archive_seq: int = 0


def _archive(mode: str) -> None:
    """Кладёт действующий рабочий файл в историю и подрезает её."""
    global _archive_seq
    cur = _runtime_path(mode)
    if not cur.exists():
        return
    hist = _history_dir()
    hist.mkdir(parents=True, exist_ok=True)
    _archive_seq += 1
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{_archive_seq:06d}"
    _atomic_write(hist / f"{mode}-{stamp}.md", cur.read_text(encoding="utf-8"))
    old = history(mode)
    for p in old[HISTORY_KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass


def history(mode: str) -> list[Path]:
    """Прежние версии режима, новые первыми."""
    _check_mode(mode)
    hist = _history_dir()
    if not hist.is_dir():
        return []
    return sorted(hist.glob(f"{mode}-*.md"), reverse=True)


def set(mode: str, text: str, *, source: str = "unknown") -> None:
    """Перезаписывает образ режима. Прежняя версия уходит в историю."""
    _check_mode(mode)
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) < MIN_CHARS:
        raise PersonaError(f"образ слишком короткий: {len(text)} симв., нужно от {MIN_CHARS}")
    if len(text) > MAX_CHARS:
        raise PersonaError(f"образ слишком длинный: {len(text)} симв., предел {MAX_CHARS}")
    with _lock:
        _archive(mode)
        _atomic_write(_runtime_path(mode), text + "\n")
    log.info("[persona] образ %s перезаписан: %d симв., источник=%s", mode, len(text), source)


def reset(mode: str, *, source: str = "unknown") -> None:
    """Возврат к заводскому образу. Рабочая версия уходит в историю."""
    _check_mode(mode)
    with _lock:
        _archive(mode)
        try:
            _runtime_path(mode).unlink()
        except FileNotFoundError:
            pass
    log.info("[persona] образ %s сброшен к заводскому, источник=%s", mode, source)


def rollback(mode: str, *, source: str = "unknown") -> bool:
    """Возвращает предыдущую версию из истории. False — истории нет."""
    _check_mode(mode)
    with _lock:
        versions = history(mode)
        if not versions:
            return False
        prev = versions[0]
        text = prev.read_text(encoding="utf-8")
        _atomic_write(_runtime_path(mode), text)
        prev.unlink()
    log.info("[persona] образ %s откатан на прежнюю версию, источник=%s", mode, source)
    return True
