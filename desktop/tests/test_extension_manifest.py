"""Полнота manifest расширения (desktop/extension): каждый упомянутый файл существует.

Без иконок в репозитории Opera не загружала распакованное расширение (.gitignore *.png).
"""
import json
import re
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "extension"


def _manifest() -> dict:
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


def _referenced_files(m: dict) -> list[str]:
    files = list(m.get("icons", {}).values())
    files += list(m.get("action", {}).get("default_icon", {}).values())
    files.append(m["background"]["service_worker"])
    for cs in m.get("content_scripts", []):
        files += cs.get("js", [])
    popup = m.get("action", {}).get("default_popup")
    if popup:
        files.append(popup)
    return files


def test_every_manifest_file_exists():
    m = _manifest()
    files = _referenced_files(m)
    assert {"icon16.png", "icon48.png", "icon128.png", "background.js", "content.js"} <= set(files)
    missing = [f for f in files if not (EXT / f).is_file()]
    assert missing == []


def test_service_worker_imports_exist():
    sw = (EXT / _manifest()["background"]["service_worker"]).read_text(encoding="utf-8")
    imports = re.findall(r'importScripts\(([^)]*)\)', sw)
    names = [n for call in imports for n in re.findall(r'"([^"]+)"', call)]
    assert names == ["lib/capture.js", "lib/agent.js"]
    assert [n for n in names if not (EXT / n).is_file()] == []


def test_icons_are_png():
    for name in ("icon16.png", "icon48.png", "icon128.png"):
        assert (EXT / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_version_and_frames():
    m = _manifest()
    assert m["version"] == "3.2.0"
    assert m["manifest_version"] == 3
    assert all(cs.get("all_frames") for cs in m["content_scripts"])
    assert {"scripting", "tabs", "webNavigation"} <= set(m["permissions"])


def test_no_eval_except_flagged_js_exec():
    """eval — только в execInTab для js_exec, и js_exec выключен флагом."""
    for path in [EXT / "content.js", EXT / "lib" / "agent.js", EXT / "lib" / "capture.js"]:
        assert "eval(" not in path.read_text(encoding="utf-8"), path.name
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert bg.count("eval(") == 1
    assert "const ALLOW_JS_EXEC = false;" in bg
    # Код в страницу строкой больше не собирается: нет execInTab с шаблонной строкой.
    assert not re.search(r"execInTab\([^)]*`", bg)
    assert "ytExec(" not in bg
