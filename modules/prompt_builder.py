"""
modules/prompt_builder.py — генерация промптов для MiMo.

Помогает Сакуре:
  - Анализировать существующий код
  - Генерировать детальные промпты для нового кода
  - Проверять результат
"""

import ast
import os
import re
from typing import Optional


def analyze_file(path: str) -> dict:
    """
    Анализирует файл и возвращает структуру.
    Нужно для понимания паттернов проекта.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Парсим AST
        tree = ast.parse(content)

        functions = []
        classes = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                funcs = [a.arg for a in node.args.args]
                functions.append({
                    "name": node.name,
                    "args": funcs,
                    "line": node.lineno,
                    "docstring": ast.get_docstring(node) or "",
                })
            elif isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                })
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                else:
                    imports.append(f"from {node.module}")

        return {
            "ok": True,
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "lines": len(content.split("\n")),
            "size": len(content),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def analyze_project(patterns: list[str] = None) -> dict:
    """
    Анализирует структуру проекта.
    Возвращает информацию о модулях и паттернах.
    """
    if patterns is None:
        patterns = ["modules/*.py", "memory/*.py"]

    project_info = {
        "modules": [],
        "patterns": [],
    }

    # Анализируем основные модули
    for pattern in patterns:
        import glob
        for path in glob.glob(os.path.join("/opt/sakura", pattern)):
            if "__pycache__" in path:
                continue
            name = os.path.basename(path)
            analysis = analyze_file(path)
            if analysis["ok"]:
                project_info["modules"].append({
                    "name": name,
                    "path": path,
                    "functions": [f["name"] for f in analysis["functions"]],
                    "size": analysis["size"],
                })

    # Определяем паттерны
    all_functions = []
    for mod in project_info["modules"]:
        all_functions.extend(mod["functions"])

    # Частые паттерны именования
    get_funcs = [f for f in all_functions if f.startswith("get_")]
    set_funcs = [f for f in all_functions if f.startswith("set_") or f.startswith("update_")]
    check_funcs = [f for f in all_functions if f.startswith("check_") or f.startswith("is_")]

    if get_funcs:
        project_info["patterns"].append(f"get_*(): {', '.join(get_funcs[:5])}")
    if set_funcs:
        project_info["patterns"].append(f"set/update_*(): {', '.join(set_funcs[:5])}")
    if check_funcs:
        project_info["patterns"].append(f"check/is_*(): { ', '.join(check_funcs[:5])}")

    return project_info


def build_module_prompt(
    name: str,
    description: str,
    functions: list[dict],
    integration: str = "",
    storage: str = "",
    example_module: str = "",
) -> str:
    """
    Генерирует детальный промпт для создания модуля.

    Args:
        name: Имя модуля (без .py)
        description: Описание что делает модуль
        functions: Список функций [{"name": ..., "args": ..., "desc": ...}]
        integration: Как интегрировать в main.py
        storage: Где хранить данные
        example_module: Путь к модулю-примеру для стиля кода
    """
    project = analyze_project()

    # Анализ примера
    example_info = ""
    if example_module and os.path.exists(example_module):
        analysis = analyze_file(example_module)
        if analysis["ok"]:
            example_info = f"""
ПАТТЕРН КОДА (из {example_module}):
- Функции: {', '.join(f['name'] for f in analysis['functions'][:5])}
- Импорты: {', '.join(analysis['imports'][:5])}
"""

    # Формируем промпт
    prompt_parts = [
        f"Создай модуль {name}.py в /opt/sakura/modules/",
        f"",
        f"ОПИСАНИЕ: {description}",
        f"",
        f"ФУНКЦИИ:",
    ]

    for func in functions:
        args = ", ".join(func.get("args", []))
        prompt_parts.append(f"  - {func['name']}({args}) — {func.get('desc', '')}")

    if storage:
        prompt_parts.extend([
            f"",
            f"ХРАНЕНИЕ: {storage}",
        ])

    if integration:
        prompt_parts.extend([
            f"",
            f"ИНТЕГРАЦИЯ В main.py:",
            f"{integration}",
        ])

    if example_info:
        prompt_parts.append(example_info)

    # Паттерны проекта
    if project.get("patterns"):
        prompt_parts.extend([
            f"",
            f"ПАТТЕРНЫ ПРОЕКТА:",
            *project["patterns"],
        ])

    # Требования к стилю
    prompt_parts.extend([
        f"",
        f"ТРЕБОВАНИЯ К СТИЛЮ:",
        f"- Только русские комментарии",
        f"- Без эмодзи",
        f"- Без markdown в коде",
        f"- Логирование через logging.getLogger",
        f"- Обработка ошибок через try/except",
        f"- Docstrings на русском",
    ])

    return "\n".join(prompt_parts)


def build_fix_prompt(path: str, error: str, context: str = "") -> str:
    """Генерирует промпт для исправления бага."""
    analysis = analyze_file(path)

    prompt_parts = [
        f"Исправь ошибку в {path}",
        f"",
        f"ОШИБКА: {error}",
    ]

    if context:
        prompt_parts.extend([
            f"",
            f"КОНТЕКСТ: {context}",
        ])

    if analysis.get("functions"):
        func_lines = [f"  - {f['name']}({', '.join(f['args'])})" for f in analysis["functions"][:10]]
        prompt_parts.extend([
            f"",
            f"ФУНКЦИИ В ФАЙЛЕ:",
            *func_lines,
        ])

    prompt_parts.extend([
        f"",
        f"ТРЕБОВАНИЯ:",
        f"- Исправь только ошибку, не меняй логику",
        f"- Сохрани стиль кода",
        f"- Добавь комментарий что было исправлено",
    ])

    return "\n".join(prompt_parts)


def build_review_prompt(path: str) -> str:
    """Генерирует промпт для ревью кода."""
    analysis = analyze_file(path)

    prompt_parts = [
        f"Проведи ревью файла {path}",
        f"",
        f"ПРОВЕРЬ:",
        f"1. Баги и ошибки",
        f"2. Проблемы безопасности",
        f"3. Производительность",
        f"4. Читаемость кода",
        f"5. Соответствие паттернам проекта",
    ]

    if analysis.get("functions"):
        func_lines = [f"  - {f['name']}" for f in analysis["functions"][:15]]
        prompt_parts.extend([
            f"",
            f"ФУНКЦИИ ДЛЯ АНАЛИЗА:",
            *func_lines,
        ])

    return "\n".join(prompt_parts)
