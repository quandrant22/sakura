"""
modules/coding.py — модуль кодинга для Сакуры.

Позволяет Сакуре:
  - Читать/править файлы на сервере
  - Запускать команды
  - Коммитить в git
  - Собирать Android приложение
  - Устанавливать APK на телефон

Использует MiMo Code как движок.
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

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


# ── Высокоуровневые функции ──────────────────────────────────────────

async def read_file(path: str) -> str:
    """Читает файл на сервере."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Ошибка чтения: {e}"


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


async def run_command(cmd: str, timeout: int = 60) -> dict:
    """Выполняет shell-команду на сервере."""
    # Проверка на опасные команды
    for dangerous in DANGEROUS_COMMANDS:
        if dangerous in cmd:
            return {"ok": False, "output": "", "error": "Опасная команда запрещена"}

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
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


# ── Git операции ─────────────────────────────────────────────────────

async def git_status() -> str:
    """Статус git."""
    r = await run_command("git status --short", cwd=PROJECT_DIR)
    return r["output"] if r["ok"] else r["error"]


async def git_diff() -> str:
    """Разница изменений."""
    r = await run_command("git diff", cwd=PROJECT_DIR)
    return r["output"] if r["ok"] else r["error"]


async def git_commit(message: str) -> str:
    """Коммитит изменения."""
    await run_command("git add -A", cwd=PROJECT_DIR)
    r = await run_command(f'git commit -m "{message}"', cwd=PROJECT_DIR)
    return r["output"] if r["ok"] else r["error"]


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


# ── MiMo кодинг ──────────────────────────────────────────────────────

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
    if content.startswith("Ошибка"):
        return content
    prompt = f"Объясни что делает этот код:\n\n{content[:3000]}"
    r = await run_mimo(prompt)
    return r["output"] if r["ok"] else r["error"]
