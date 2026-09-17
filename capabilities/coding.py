"""Домен «кодинг» (этап 6, коммит 7B-3): coding.* — executor=vps.

Кодинговые операции: создание модулей, фикс багов, чтение файлов, коммиты,
сборка. Реализация живёт НА СЕРВЕРЕ (этап 7, развязка восьми недостижимых
id): MiMo Code запускается здесь же, в /opt/sakura, поэтому executor=vps,
а не agent. Переучивать второй рантайм (Windows) тому, что уже работает
на VPS, — лишний источник расхождений.

До этого кодинг жил в modules/coding.py и вызывался по подстроке из
modules/ws_handlers.py — мимо реестра. Поэтому шесть coding.* id реестра
были недостижимы: агент их не исполняет (в agent/core/hands.py нет verb'ов
coding.*, в _legacy_action нет маппинга), а мост возвращал (False, None).

Перенос сохраняет поведение ветки ws_handlers.py:311-355:
  coding.create_module → mimo_fix(«Создай новый модуль по запросу Мастера: …»)
  coding.fix           → mimo_fix(«Найди и исправь проблему: …»)
  coding.commit        → git_commit(сообщение)
Плюс то, что реестр обещал, но старый путь не делал вовсе:
  coding.read_file → содержимое файла, coding.git_status → git status,
  coding.build     → android_build().

Контракт хендлеров — (текст, ok), как у VPS-доменов (capabilities/_vps.py):
ok=False значит «источник или команда недоступны», и это говорится прямо,
а не маскируется под «нет данных».

Реализация и таблица хендлеров находятся здесь; старый modules/coding.py удалён.
"""

import asyncio
import logging
import os
import subprocess
from typing import Optional

from sakura_core.executor import ExecutionContext, Handler, register_table

log = logging.getLogger("sakura.coding")

# Пути
MIMO_BIN = os.path.expanduser("~/.mimocode/bin/mimo")
PROJECT_DIR = "/opt/sakura"
ANDROID_PROJECT = os.getenv("ANDROID_PROJECT", "")  # Путь к проекту Android

# Опасные команды — запрещены
DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # fork bomb
    "chmod -R 777 /",
    "wget | bash",
    "curl | bash",
]

# Префикс, которым read_file сообщает о недоступности источника (см. ниже).
READ_ERROR_PREFIX = "Ошибка чтения:"


def is_available() -> bool:
    """Проверяет доступность MiMo."""
    return os.path.isfile(MIMO_BIN) and os.access(MIMO_BIN, os.X_OK)


def _run_mimo(prompt: str, work_dir: str = PROJECT_DIR,
              timeout: int = 300, dangerous: bool = False) -> dict:
    """
    Запускает MiMo Code с промптом.
    Возвращает {"ok": bool, "output": str, "error": str}
    """
    if not is_available():
        return {"ok": False, "output": "", "error": "MiMo не установлен"}

    cmd = [
        MIMO_BIN, "run", prompt,
        "--format", "json",
        "--dir", work_dir,
    ]
    if dangerous:
        cmd.append("--dangerously-skip-permissions")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        return {
            "ok": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"Таймаут {timeout}с"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


async def run_mimo(prompt: str, work_dir: str = PROJECT_DIR,
                   timeout: int = 300, dangerous: bool = False) -> dict:
    """Асинхронная обёртка для _run_mimo."""
    return await asyncio.to_thread(_run_mimo, prompt, work_dir, timeout, dangerous)

# ── Работа с файлами сервера ────────────────────────────────────────

async def read_file(path: str) -> str:
    """Читает файл на сервере. Ошибка источника — текстом с READ_ERROR_PREFIX."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"{READ_ERROR_PREFIX} {e}"


async def write_file(path: str, content: str) -> bool:
    """Записывает файл на сервере."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        log.error(f"[coding] Ошибка записи {path}: {e}")
        return False


async def edit_file(path: str, old_text: str, new_text: str) -> bool:
    """Правит файл на сервере (поиск и замена)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old_text not in content:
            return False
        content = content.replace(old_text, new_text, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        log.error(f"[coding] Ошибка правки {path}: {e}")
        return False


# ── Команды и git ───────────────────────────────────────────────────

async def run_command(cmd: str, timeout: int = 60,
                      cwd: Optional[str] = None) -> dict:
    """Выполняет shell-команду на сервере.

    cwd добавлен при переносе (этап 7E): git_* и android_build вызывали
    run_command(..., cwd=PROJECT_DIR) ещё в modules/coding.py, но такого
    параметра не было — TypeError на каждом вызове. subprocess.run вынесен
    в поток: команда с timeout=600 не должна держать event loop.
    """
    # Проверка на опасные команды
    for dangerous in DANGEROUS_COMMANDS:
        if dangerous in cmd:
            return {"ok": False, "output": "", "error": "Опасная команда запрещена"}

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, shell=True, capture_output=True,
            text=True, timeout=timeout, cwd=cwd,
        )
        return {
            "ok": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "", "error": f"Таймаут {timeout}с"}
    except Exception as e:
        return {"ok": False, "output": "", "error": str(e)}


async def git_status_result() -> tuple[str, bool]:
    """Статус git с честным ok: ok=False — команда не выполнилась."""
    r = await run_command("git status --short", cwd=PROJECT_DIR)
    if not r["ok"]:
        return (f"git status не выполнился: {r['error'].strip()[:200]}", False)
    return (r["output"].strip() or "Изменений нет — рабочее дерево чистое.", True)


async def git_commit_result(message: str) -> tuple[str, bool]:
    """Коммит с честным ok: ok=False — git вернул ошибку."""
    add = await run_command("git add -A", cwd=PROJECT_DIR)
    if not add["ok"]:
        return (f"git add не выполнился: {add['error'].strip()[:200]}", False)
    r = await run_command(f'git commit -m "{message}"', cwd=PROJECT_DIR)
    if not r["ok"]:
        detail = (r["error"] or r["output"]).strip()[:300]
        return (f"Коммит не сделан: {detail}", False)
    return (f"Коммит выполнен: {r['output'].strip()[:200]}", True)


# Строковые формы — совместимость с modules/ws_handlers.py до его удаления.
async def git_status() -> str:
    """Статус git строкой."""
    text, _ = await git_status_result()
    return text


async def git_diff() -> str:
    """Разница изменений."""
    r = await run_command("git diff", cwd=PROJECT_DIR)
    return r["output"] if r["ok"] else r["error"]


async def git_commit(message: str) -> str:
    """Коммитит изменения, отдаёт текст результата."""
    text, _ = await git_commit_result(message)
    return text


async def git_push() -> str:
    """Пушит в remote."""
    r = await run_command("git push", cwd=PROJECT_DIR)
    return r["output"] if r["ok"] else r["error"]
# ── Автоинтеграция модулей ──────────────────────────────────────────

async def auto_integrate(module_name: str, description: str = "") -> dict:
    """
    Автоматически интегрирует новый модуль в main.py:
    1. Добавляет import
    2. Добавляет вызов в _build_system()
    3. Добавляет в _voice_modules для голосовых команд

    ЛЕГАСИ: правит разметку main.py образца до этапа 6 (_build_system,
    _voice_modules, порядок импортов). После сворачивания main.py в точку
    входа эта разметка исчезла, поэтому в v3 вызывающих у функции нет —
    перенесена как есть, чтобы не терять поведение при переезде домена.
    """
    main_path = os.path.join(PROJECT_DIR, "main.py")

    try:
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()

        changes = []

        # 1. Добавляем import
        import_line = f"from modules.{module_name} import get_context_for_prompt as get_{module_name}_ctx"
        if import_line not in content:
            import re
            marker_pattern = r"\n# ────"
            match = re.search(marker_pattern, content)
            if match:
                insert_pos = match.start()
                content = content[:insert_pos] + "\n" + import_line + content[insert_pos:]
                changes.append("import добавлен")

        # 2. Добавляем вызов в _build_system()
        call_block = f"""
    # {module_name}
    try:
        from modules.{module_name} import get_context_for_prompt as get_{module_name}_ctx
        {module_name}_ctx = get_{module_name}_ctx()
        if {module_name}_ctx:
            parts.append({module_name}_ctx)
    except Exception:
        pass
"""
        marker_build = "if include_calendar:"
        if marker_build in content and f"modules.{module_name}" not in content.split(marker_build)[0][-500:]:
            content = content.replace(marker_build, call_block + "\n    " + marker_build)
            changes.append("вызов в _build_system() добавлен")

        # 3. Добавляем в _voice_modules
        voice_marker = '_voice_modules = ['
        if voice_marker in content:
            # Проверяем не добавлен ли уже
            voice_section = content[content.index(voice_marker):content.index(voice_marker) + 500]
            if f'"{module_name}"' not in voice_section:
                # Вставляем перед ]
                insert_pos = content.index(voice_marker) + len(voice_marker)
                content = content[:insert_pos] + f'"{module_name}", ' + content[insert_pos:]
                changes.append("добавлен в _voice_modules")

        if changes:
            with open(main_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "changes": changes}
        else:
            return {"ok": True, "changes": ["уже интегрирован"]}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Android сборка ───────────────────────────────────────────────────

async def android_build() -> dict:
    """Собирает Android APK."""
    if not ANDROID_PROJECT:
        return {"ok": False, "error": "ANDROID_PROJECT не задан"}

    gradlew = os.path.join(ANDROID_PROJECT, "gradlew")
    if not os.path.isfile(gradlew):
        return {"ok": False, "error": "gradlew не найден"}

    r = await run_command(f"{gradlew} assembleDebug", cwd=ANDROID_PROJECT, timeout=600)
    return r


async def android_install() -> dict:
    """Устанавливает APK на телефон через ADB."""
    if not ANDROID_PROJECT:
        return {"ok": False, "error": "ANDROID_PROJECT не задан"}

    # Ищем APK
    apk_dir = os.path.join(ANDROID_PROJECT, "app/build/outputs/apk/debug")
    if not os.path.isdir(apk_dir):
        return {"ok": False, "error": "APK не найден"}

    apk_files = [f for f in os.listdir(apk_dir) if f.endswith(".apk")]
    if not apk_files:
        return {"ok": False, "error": "APK файл не найден"}

    apk_path = os.path.join(apk_dir, apk_files[0])
    r = await run_command(f"adb install -r {apk_path}")
    return r


# ─ MiMo кодинг ──────────────────────────────────────────────────────

async def mimo_fix(prompt: str) -> dict:
    """
    Запускает MiMo для исправления бага.
    Пример: mimo_fix("исправь ошибку в modules/weather.py")
    """
    return await run_mimo(prompt, dangerous=True)


async def mimo_review(path: str) -> dict:
    """Запрашивает ревью кода у MiMo."""
    prompt = f"Проведи ревью файла {path}. Найди баги, улучшения, проблемы."
    return await run_mimo(prompt)


async def mimo_explain(path: str) -> str:
    """Объясняет код в файле."""
    content = await read_file(path)
    if content.startswith(READ_ERROR_PREFIX):
        return content
    prompt = f"Объясни что делает этот код:\n\n{content[:3000]}"
    r = await run_mimo(prompt)
    return r["output"] if r["ok"] else r["error"]
# ── Хендлеры реестра: coding.* (executor=vps) ────────────────────────

def _master_text(ctx: ExecutionContext) -> str:
    """Исходная фраза Мастера: старый путь гнал в MiMo весь текст целиком."""
    return ((ctx.extra or {}).get("text") or "").strip()


def _mimo_reply(result: dict) -> tuple[str, bool]:
    """Ответ MiMo → (текст, ok): та же выдача, что была в ветке ws_handlers."""
    if result.get("ok"):
        return (result.get("output", "")[:1500], True)
    return (f"Ошибка: {result.get('error', 'неизвестно')}", False)


async def _create_module(ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.create_module: MiMo создаёт модуль по фразе Мастера."""
    text = _master_text(ctx)
    prompt = (f"Создай новый модуль по запросу Мастера: {text}. "
              f"Автоматически интегрируй в main.py через auto_integrate().")
    log.info(f"[coding] создаю модуль: {text[:50]}")
    return _mimo_reply(await mimo_fix(prompt))


async def _fix(ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.fix: MiMo ищет и правит проблему по фразе Мастера."""
    text = _master_text(ctx)
    prompt = f"Найди и исправь проблему: {text}"
    log.info(f"[coding] исправляю баг: {text[:50]}")
    return _mimo_reply(await mimo_fix(prompt))


async def _read_code_file(ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.read_file: показать код файла (param: filepath).

    Старый путь эти фразы («прочитай файл», «покажи код») только ловил,
    но ничего не делал — реестр обещал больше, чем было.
    """
    content = await read_file(ctx.param or "")
    return (content, not content.startswith(READ_ERROR_PREFIX))


async def _commit(ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.commit: git add -A + commit (param: message)."""
    message = (ctx.param or "").strip() or "Обновление от Сакуры"
    return await git_commit_result(message)


async def _build(ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.build: собрать APK (android_build)."""
    r = await android_build()
    if not r.get("ok"):
        return (f"Сборка не прошла: {r.get('error', 'неизвестно')}", False)
    out = (r.get("output") or "").strip()
    return (f"Сборка завершена: {out[-300:]}" if out else "Сборка завершена.", True)


async def _git_status(_ctx: ExecutionContext) -> tuple[str, bool]:
    """coding.git_status: показать git status."""
    return await git_status_result()


CODING_HANDLERS: dict[str, Handler] = {
    "coding.create_module": _create_module,
    "coding.fix": _fix,
    "coding.read_file": _read_code_file,
    "coding.commit": _commit,
    "coding.build": _build,
    "coding.git_status": _git_status,
}

register_table(CODING_HANDLERS)
