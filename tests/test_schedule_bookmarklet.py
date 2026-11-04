"""Сборка букмарклета: подстановки, токен только в результате, совпадение с config."""
import importlib.util
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

import config

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "tools" / "schedule_bookmarklet" / "build.py"


def _mod():
    spec = importlib.util.spec_from_file_location("bm_build", BUILD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_defaults_match_config():
    f = _mod().DEFAULT_FORM
    assert (f["branch"], f["faculty"], f["year"], f["studyform"], f["groupname"]) == (
        config.MUIV_BRANCH, config.MUIV_FACULTY, config.MUIV_YEAR, config.MUIV_STUDYFORM,
        config.MUIV_GROUP)
    assert f["el"] == "groupnames"


def test_source_has_no_secrets_only_placeholders():
    src = (BUILD.parent / "bookmarklet.js").read_text(encoding="utf-8")
    assert "__TOKEN__" in src and "__ENDPOINT__" in src and "__FORM__" in src
    assert "document.cookie" not in src


def test_build_substitutes():
    m = _mod()
    out = m.build("https://sakura.example/schedule/push", "tok-123", m.DEFAULT_FORM)
    assert out.startswith("javascript:")
    js = unquote(out[len("javascript:"):])
    assert '"tok-123"' in js and '"https://sakura.example/schedule/push"' in js
    assert '"groupname": "ИД 86.1/М1-25"' in js
    assert "__" not in js.replace("__ENDPOINT__", "")  # плейсхолдеров не осталось
    assert "\n" not in js and "//" not in js.replace("https://", "")


def test_build_requires_https_and_token():
    m = _mod()
    with pytest.raises(ValueError):
        m.build("http://x/schedule/push", "t", m.DEFAULT_FORM)
    with pytest.raises(ValueError):
        m.build("https://x/schedule/push", "", m.DEFAULT_FORM)


def test_env_override():
    m = _mod()
    assert m.form_from_env({"MUIV_GROUP": "ИДс 30.1/Б6-25"})["groupname"] == "ИДс 30.1/Б6-25"


@pytest.mark.skipif(shutil.which("node") is None, reason="нет node")
def test_built_js_parses(tmp_path):
    m = _mod()
    js = unquote(m.build("https://s.example/schedule/push", "t", m.DEFAULT_FORM)[len("javascript:"):])
    f = tmp_path / "b.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
