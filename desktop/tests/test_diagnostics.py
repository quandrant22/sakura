"""Диагностика, просмотр журнала и обновление через git (на подставном git и временном журнале)."""
import asyncio
import json
import os

import pytest

from desktop.core import config
from desktop.core.api.server import ApiError
from desktop.core.service import CoreService


def svc():
    s = CoreService.__new__(CoreService)
    s.link = type("L", (), {"state_event": lambda self: {"server": "offline", "proto": None}})()
    return s


def test_logs_tail_hides_secret_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
    text = "обычная строка\nWS_TOKEN=abc123\n[api] password=x\nещё строка\n"
    (tmp_path / "sakura.log").write_text(text, encoding="utf-8")
    out = asyncio.run(svc().cmd_logs_tail({"n": 50}))
    assert out["lines"][0] == "обычная строка" and out["lines"][-1] == "ещё строка"
    assert "abc123" not in " ".join(out["lines"]) and out["lines"][1].startswith("[строка скрыта")


def test_logs_tail_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path / "нет"))
    assert asyncio.run(svc().cmd_logs_tail({}))["lines"] == []


class Git:
    def __init__(self, behind=2, dirty="", pull_code=0):
        self.behind, self.dirty, self.pull_code = behind, dirty, pull_code
        self.calls = []

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        if args[0] == "rev-parse":
            return 0, "feat/desktop-rewrite"
        if args[0] == "rev-list":
            return 0, f"0\t{self.behind}"
        if args[0] == "status":
            return 0, self.dirty
        if args[0] == "pull":
            return self.pull_code, ""
        return 0, ""


def test_update_status_and_pull_ff_only(monkeypatch):
    g = Git(behind=2)
    monkeypatch.setattr(CoreService, "_git", staticmethod(g))
    st = asyncio.run(svc().cmd_update_status({}))
    assert {k: st[k] for k in ("branch", "behind", "ahead", "dirty")} == {
        "branch": "feat/desktop-rewrite", "behind": 2, "ahead": 0, "dirty": False}
    from desktop.core import support
    seen = []
    monkeypatch.setattr(support, "update_with_rollback", lambda branch, d: seen.append(branch) or {"updated": True})
    out = asyncio.run(svc().cmd_update_pull({}))
    assert out["updated"] is True and seen == ["feat/desktop-rewrite"]


def test_update_refuses_with_local_changes(monkeypatch):
    monkeypatch.setattr(CoreService, "_git", staticmethod(Git(dirty=" M desktop/core/agent.py")))
    with pytest.raises(ApiError) as e:
        asyncio.run(svc().cmd_update_pull({}))
    assert e.value.code == "conflict"


def test_update_nothing_to_pull(monkeypatch):
    g = Git(behind=0)
    monkeypatch.setattr(CoreService, "_git", staticmethod(g))
    assert asyncio.run(svc().cmd_update_pull({}))["updated"] is False
    assert not any(c[0] == "pull" for c in g.calls)


def test_diagnostics_no_secrets(monkeypatch):
    out = asyncio.run(svc().cmd_diagnostics({}))
    assert out["pid"] == os.getpid() and "token" not in repr(out).lower()


# ── обновление с откатом и отчёт о проблеме (support) ──
class FakeGit:
    def __init__(self):
        self.head, self.calls = "aaa", []

    def __call__(self, *args, **k):
        self.calls.append(args)
        if args[0] == "rev-parse":
            return 0, self.head
        if args[0] == "pull":
            self.head = "bbb"
        if args[:2] == ("reset", "--keep"):
            self.head = args[2]
        return 0, ""


def test_update_rollback_when_build_fails(tmp_path):
    from desktop.core import support
    g, builds = FakeGit(), []
    def build():  # первая сборка (новая версия) падает, вторая (прежняя) — проходит
        builds.append(1)
        return len(builds) > 1
    out = support.update_with_rollback("b", str(tmp_path), git_fn=g, build_fn=build)
    assert out["rolled_back"] is True and g.head == "aaa" and ("reset", "--keep", "aaa") in g.calls
    assert not any(c[:2] == ("reset", "--hard") for c in g.calls)
    assert not (tmp_path / "update_pending.json").exists()


def test_update_success_leaves_marker_then_confirmed(tmp_path):
    from desktop.core import support
    out = support.update_with_rollback("b", str(tmp_path), git_fn=FakeGit(), build_fn=lambda: True)
    marker = json.loads((tmp_path / "update_pending.json").read_text(encoding="utf-8"))
    assert out["updated"] and marker["prev"] == "aaa" and marker["new"] == "bbb"
    support.confirm_started(str(tmp_path))
    assert not (tmp_path / "update_pending.json").exists()


def test_problem_report_without_secrets_and_chat(tmp_path):
    import zipfile

    from desktop.core import support
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sakura.log").write_text("старт ядра\nWS_TOKEN=abcdef\n[chat] user: мой пароль от почты\n"
                                     "[STT] Распознано: позвони маме\nконец\n", encoding="utf-8")
    path = support.problem_report(str(logs), str(tmp_path / "out"), {"device_id": "pc"})
    with zipfile.ZipFile(path) as z:
        text = z.read("sakura.log").decode("utf-8")
        assert "versions.json" in z.namelist()
    assert "старт ядра" in text and "конец" in text
    assert "abcdef" not in text and "почты" not in text and "маме" not in text
