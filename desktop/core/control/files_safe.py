"""Безопасные файловые действия: поиск только в разрешённых папках, защита путей, журнал удалений.

Разрушительные действия (удаление, перенос, перезапись) — только по полному существующему абсолютному
пути; имя без пути — никогда (живая проверка 14.10: индекс на «copy.txt» нашёл cpu.txt).
Запрещено: Windows, Program Files, ProgramData, корень профиля, папки Сакуры, исполняемые файлы;
пути с «..», символическими ссылками и точками соединения отклоняются (без обхода).
Журнал удалений (deleted.json в DATA_DIR) хранит только путь и время — без содержимого.
"""
import json
import os
import time

EXEC_EXT = frozenset({".exe", ".dll", ".sys", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".js", ".scr",
                      ".lnk", ".reg", ".jar", ".cpl", ".drv", ".ocx", ".psm1", ".wsf", ".hta"})
KNOWN_FOLDERS = ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music")
MAX_CANDIDATES = 3
MAX_SCAN = 20000
MAX_DEPTH = 6
UNDELETE_N = 5
UNDELETE_WINDOW_S = 24 * 3600


class PathRefused(ValueError):
    """Путь нельзя трогать — текст объясняет почему (без содержимого файла)."""


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def allowed_roots(env=None) -> list[str]:
    env = env or os.environ
    home = env.get("USERPROFILE", "")
    roots = [os.path.join(home, f) for f in KNOWN_FOLDERS]
    one = env.get("OneDrive")
    if one:
        roots += [os.path.join(one, f) for f in ("Documents", "Desktop", "Pictures")]
    return [r for r in roots if r]


def forbidden_roots(env=None) -> list[str]:
    env = env or os.environ
    out = [env.get("SystemRoot", r"C:\Windows"), env.get("ProgramFiles", r"C:\Program Files"),
           env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), env.get("ProgramData", r"C:\ProgramData"),
           os.path.join(env.get("LOCALAPPDATA", ""), "Sakura"), r"C:\sakura-dev", r"C:\sakura-git",
           os.path.join(env.get("USERPROFILE", ""), "AppData")]
    return [p for p in out if p]


def _under(path: str, root: str) -> bool:
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def _has_link(path: str) -> bool:
    """Символическая ссылка или точка соединения в любом звене пути."""
    # Python 3.11: isjunction нет, islink точку соединения не видит — сравниваем с реальным путём.
    try:
        if _norm(os.path.realpath(path)) != _norm(path):
            return True
    except OSError:
        return True
    cur = path
    while True:
        try:
            if os.path.islink(cur) or (hasattr(os.path, "isjunction") and os.path.isjunction(cur)):
                return True
        except OSError:
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def check_path(path: str, env=None, must_exist=True, allow_exec=False) -> str:
    """Проверенный абсолютный путь или PathRefused."""
    env = env or os.environ
    raw = (path or "").strip().strip('"')
    if not raw:
        raise PathRefused("нужен полный путь к файлу")
    if not os.path.isabs(raw) or raw.startswith("\\\\"):
        raise PathRefused("нужен полный путь к файлу (например C:\\Users\\…\\Загрузки\\файл.txt) — по имени не трогаю")
    parts = raw.replace("/", "\\").split("\\")
    if ".." in parts or "." in parts:
        raise PathRefused("путь с «..» не принимаю")
    full = os.path.normpath(raw)
    if _has_link(full):
        raise PathRefused("путь проходит через символическую ссылку — не трогаю")
    for root in forbidden_roots(env):
        if _under(full, root):
            raise PathRefused("это системная папка или папка Сакуры — не трогаю")
    home = env.get("USERPROFILE", "")
    if home and _norm(os.path.dirname(full)) == _norm(home):
        raise PathRefused("файлы в корне профиля не трогаю")
    if _norm(full) in (_norm(home), _norm(os.path.splitdrive(full)[0] + "\\")):
        raise PathRefused("корень диска или профиля не трогаю")
    if not allow_exec and os.path.splitext(full)[1].lower() in EXEC_EXT:
        raise PathRefused("исполняемые файлы и ярлыки не трогаю")
    if must_exist and not os.path.isfile(full):
        raise PathRefused("файл не найден по этому пути")
    return full


def find(name: str, folder: str | None = None, env=None) -> list[dict]:
    """До 3 кандидатов {path, size, mtime} в разрешённых папках (или названной); точное имя — первым."""
    env = env or os.environ
    want = (name or "").strip().lower()
    if not want:
        return []
    roots = allowed_roots(env)
    if folder:
        f = os.path.normpath(folder.strip().strip('"'))
        if not os.path.isabs(f) or any(_under(f, r) for r in forbidden_roots(env)) or _has_link(f) \
                or _norm(f) == _norm(os.path.splitdrive(f)[0] + "\\"):
            raise PathRefused("в этой папке искать не буду")
        roots = [f]
    exact, partial, scanned = [], [], 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if dirpath.count(os.sep) - base_depth >= MAX_DEPTH:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                scanned += 1
                low = fn.lower()
                if low == want or os.path.splitext(low)[0] == want:
                    exact.append(os.path.join(dirpath, fn))
                elif want in low:
                    partial.append(os.path.join(dirpath, fn))
            if scanned >= MAX_SCAN or len(exact) >= MAX_CANDIDATES:
                break
    out = []
    for p in (exact + partial)[:MAX_CANDIDATES]:
        try:
            st = os.stat(p)
            out.append({"path": p, "size": st.st_size, "mtime": int(st.st_mtime)})
        except OSError:
            continue
    return out


# ── журнал удалений (только путь и время) ──
class DeleteJournal:
    def __init__(self, path: str, clock=time.time):
        self.path = path
        self.clock = clock

    def _load(self) -> list[dict]:
        try:
            data = json.load(open(self.path, encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def add(self, file_path: str) -> None:
        items = [e for e in self._load() if self.clock() - e.get("t", 0) < UNDELETE_WINDOW_S][-50:]
        items.append({"path": file_path, "t": self.clock()})
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

    def recent(self, n: int = UNDELETE_N) -> list[dict]:
        now = self.clock()
        return [e for e in self._load() if now - e.get("t", 0) < UNDELETE_WINDOW_S and not e.get("restored")][-n:]

    def mark_restored(self, file_path: str) -> None:
        items = self._load()
        for e in reversed(items):
            if e.get("path") == file_path and not e.get("restored"):
                e["restored"] = True
                break
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)


def default_journal() -> DeleteJournal:
    from desktop.core import config
    return DeleteJournal(os.path.join(config.DATA_DIR, "deleted.json"))
