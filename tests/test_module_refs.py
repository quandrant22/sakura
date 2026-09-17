"""Resolve lazy from-imports without having to execute infinite loops.

All project sources are parsed. Runtime resolution is environment-specific:
Windows agent/experimental desktop tools need their own Windows dependency set.
They are listed explicitly, never represented by mocked successful imports.
"""
import ast
import importlib
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", "node_modules"}


def sources():
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(directory) / name


def lazy_imports(tree):
    """Visit each node once, including nested async functions and methods."""
    found = []

    class Visitor(ast.NodeVisitor):
        depth = 0

        def visit_FunctionDef(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ImportFrom(self, node):
            if self.depth:
                found.append(node)

    Visitor().visit(tree)
    return found


def resolve_import(node, package):
    name = "." * node.level + (node.module or "")
    module_name = importlib.util.resolve_name(name, package) if node.level else name
    module = importlib.import_module(module_name)
    errors = []
    for alias in node.names:
        try:
            if alias.name == "*":
                for exported in getattr(module, "__all__", ()):
                    getattr(module, exported)
            elif not hasattr(module, alias.name):
                # Python's from-package import also resolves submodules.
                if hasattr(module, "__path__"):
                    importlib.import_module(f"{module_name}.{alias.name}")
                else:
                    getattr(module, alias.name)
        except Exception as exc:
            errors.append(f"{alias.name}: {type(exc).__name__}: {exc}")
    return errors


def test_lazy_imports_resolve():
    failures, unavailable = [], []
    checked = 0
    for path in sources():
        relative = path.relative_to(ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        nodes = lazy_imports(tree)
        # These are separate applications, not importable VPS modules.
        if relative.parts[0] == "agent" or relative.parts[:2] == ("docs", "experimental"):
            unavailable.extend(f"{relative}:{n.lineno}" for n in nodes)
            continue
        package = ".".join(relative.parts[:-1])
        for node in nodes:
            # This test deliberately installs agent/ as its import root.
            # Resolving it as a VPS package would report a false missing core.
            if relative.as_posix() == "tests/test_translit.py" and node.module == "core":
                unavailable.append(f"{relative}:{node.lineno} (agent import root)")
                continue
            checked += 1
            try:
                errors = resolve_import(node, package)
            except Exception as exc:
                errors = [f"{type(exc).__name__}: {exc}"]
            failures.extend(f"{path}:{node.lineno}: {ast.unparse(node)} — {error}"
                            for error in errors)
    print(f"Lazy imports: checked={checked}, failures={failures}")
    print(f"Separate desktop applications (not runtime-checked on {sys.platform}): {len(unavailable)} imports")
    assert not failures, "\n" + "\n".join(failures)


def test_scanner_finds_nested_and_async_imports():
    tree = ast.parse("async def outer():\n from os import path as p\n def inner():\n  from sys import version\n")
    assert [n.module for n in lazy_imports(tree)] == ["os", "sys"]


def test_scanner_reports_unknown_names_and_resolves_submodules():
    node = ast.parse("from os import sakura_nonexistent_symbol").body[0]
    assert resolve_import(node, "")
    node = ast.parse("from email import mime").body[0]
    assert resolve_import(node, "") == []


def test_no_production_module_imports_main():
    failures = []
    for path in sources():
        if path.relative_to(ROOT).parts[0] in {"tests", "agent", "docs"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "main":
                failures.append(f"{path}:{node.lineno}")
            elif isinstance(node, ast.Import) and any(a.name == "main" for a in node.names):
                failures.append(f"{path}:{node.lineno}")
    assert not failures, failures
