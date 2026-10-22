"""desktop.core.support — обновление с откатом и «Отчёт о проблеме».

Обновление: прежний коммит запоминается в update_pending.json (DATA_DIR) → git pull --ff-only → сборка
интерфейса (npm run build). Сборка упала — откат: git reset --keep <прежний> и сборка прежней версии.
После перезапуска лаунчер проверяет метку: ядро не поднялось за 90 с — тот же откат (launch.ps1).
reset --keep, а не --hard: при локальных изменениях он отказывается (обновление по кнопке их и так не допускает).

Отчёт о проблеме: zip в DATA_DIR\\reports — журналы и версии. Строки со служебными данными (token, key,
secret, password) и с содержимым разговора (распознанный текст, ответы, сообщения чата) вырезаются.
"""
import json
import os
import platform
import re
import subprocess
import sys
import time
import zipfile

SECRET_WORDS = ("token", "key", "secret", "password", "пароль", "authorization")
CHAT_MARKERS = ("[chat]", "[stt]", "распознано", "user_text", "sakura_text", "reply", "transcript", "[voice] текст",
                "сказал", "фраза:", "chat_message")
LOG_FILES = ("sakura.log", "sakura.log.1", "core-console.log", "launcher.log", "build.log", "crash.log")


def repo_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def git(*args, timeout=120, cwd=None) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", cwd or repo_dir(), *args], capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or r.stderr).strip()


def npm_build(timeout=600) -> bool:
    ui = os.path.join(repo_dir(), "desktop", "ui")
    r = subprocess.run("npm run build", cwd=ui, shell=True, capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def pending_path(data_dir: str) -> str:
    return os.path.join(data_dir, "update_pending.json")


def update_with_rollback(branch: str, data_dir: str, git_fn=git, build_fn=npm_build, clock=time.time) -> dict:
    """Перемотка вперёд + сборка; при провале сборки — откат на прежний коммит."""
    code, prev = git_fn("rev-parse", "HEAD")
    if code:
        return {"updated": False, "detail": "не удалось определить текущую версию"}
    code, _ = git_fn("pull", "--ff-only", "origin", branch)
    if code:
        return {"updated": False, "detail": "обновление не прошло (не перемотка вперёд) — нужна ручная проверка"}
    _, new = git_fn("rev-parse", "HEAD")
    if not build_fn():
        git_fn("reset", "--keep", prev)
        build_fn()
        return {"updated": False, "rolled_back": True,
                "detail": "новая версия не собралась — вернула прежнюю, Сакура работает как раньше"}
    os.makedirs(data_dir, exist_ok=True)
    with open(pending_path(data_dir), "w", encoding="utf-8") as f:
        json.dump({"prev": prev, "new": new, "ts": clock()}, f)
    return {"updated": True, "restart": True, "detail": "обновлено. Перезапустите Сакуру — если она не запустится, "
                                                         "при следующем запуске вернётся прежняя версия"}


def confirm_started(data_dir: str) -> None:
    """Ядро после обновления поднялось — метка больше не нужна (откат не потребуется)."""
    try:
        os.remove(pending_path(data_dir))
    except OSError:
        pass


def _clean(line: str) -> str | None:
    low = line.lower()
    if any(w in low for w in SECRET_WORDS):
        return "[строка скрыта: служебные данные]"
    if any(m in low for m in CHAT_MARKERS):
        return "[строка скрыта: содержимое разговора]"
    return line


def problem_report(log_dir: str, out_dir: str, extra: dict | None = None, clock=time.time) -> str:
    """Архив журналов и версий без секретов и без содержимого разговора; возвращает путь."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    path = os.path.join(out_dir, f"sakura-report-{stamp}.zip")
    try:
        commit = git("rev-parse", "--short", "HEAD")[1]
    except (OSError, subprocess.SubprocessError):
        commit = ""
    info = {"time": stamp, "commit": commit, "python": sys.version.split()[0], "os": platform.platform(),
            **(extra or {})}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("versions.json", json.dumps(info, ensure_ascii=False, indent=1))
        for name in LOG_FILES:
            src = os.path.join(log_dir, name)
            if not os.path.isfile(src):
                continue
            with open(src, encoding="utf-8", errors="replace") as f:
                lines = [c for c in (_clean(ln.rstrip("\n")) for ln in f.readlines()[-5000:]) if c is not None]
            z.writestr(name, "\n".join(lines))
    return path


_TOKENISH = re.compile(r"[A-Za-z0-9_\-]{32,}")


def looks_clean(text: str) -> bool:
    """Проверка для тестов и самоконтроля: в отчёте нет длинных токеноподобных строк."""
    return not _TOKENISH.search(text)
