"""Безопасные файловые действия на временном профиле (настоящих пользовательских файлов не касается)."""
import _winapi
import os
from types import SimpleNamespace

import pytest

from desktop.core.control import files_safe as F
from desktop.core.control import registry as reg
from desktop.core.control import safety


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "Users" / "U"
    for d in ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music", "AppData/Local/Sakura"):
        (h / d).mkdir(parents=True)
    env = {"USERPROFILE": str(h), "LOCALAPPDATA": str(h / "AppData" / "Local"),
           "SystemRoot": str(tmp_path / "Windows"), "ProgramFiles": str(tmp_path / "PF"),
           "ProgramFiles(x86)": str(tmp_path / "PF86"), "ProgramData": str(tmp_path / "PD")}
    for d in ("Windows", "PF", "PD"):
        (tmp_path / d).mkdir()
    return h, env


class Plat:
    def __init__(self):
        self.recycled, self.restored = [], []
        self.bin = {}

    def recycle(self, p):
        self.recycled.append(p)
        self.bin[p] = open(p, "rb").read()
        os.remove(p)
        return True

    def restore_from_recycle(self, p):
        if p not in self.bin:
            return False
        open(p, "wb").write(self.bin.pop(p))
        self.restored.append(p)
        return True

    def reveal(self, p):
        return True


def ctx(env, tmp_path, clock=None):
    j = F.DeleteJournal(str(tmp_path / "deleted.json"), clock=clock or (lambda: 1000.0))
    c = reg.Ctx(platform=Plat(), fs=SimpleNamespace(copy=lambda s, d: open(d, "wb").write(open(s, "rb").read()),
                                                    move=lambda s, d: os.replace(s, d)))
    c.extra = {"env": env, "journal": j}
    return c


def run(action, arg, c, confirmed=False):
    return reg.execute(action, arg, confirmed, ctx=c, limiter=safety.RateLimiter(limit=1000))


# ── защита путей ──
def test_check_path_refusals(home, tmp_path):
    h, env = home
    good = h / "Downloads" / "отчёт.txt"
    good.write_text("x")
    assert F.check_path(str(good), env=env) == str(good)
    cases = {
        "отчёт.txt": "полный путь",                                      # имя без пути
        str(h / "Downloads" / ".." / "Downloads" / "отчёт.txt"): "..",   # обход через ..
        str(tmp_path / "Windows" / "a.txt"): "системная",
        str(tmp_path / "PF" / "a.txt"): "системная",
        str(h / "AppData" / "Local" / "Sakura" / "layout.json"): "системная",
        str(h / "a.txt"): "корне профиля",
        str(h / "Downloads" / "setup.exe"): "исполняемые",
        str(h / "Downloads" / "run.bat"): "исполняемые",
        str(h / "Downloads" / "нет.txt"): "не найден",
    }
    for p, why in cases.items():
        with pytest.raises(F.PathRefused, match=why):
            F.check_path(p, env=env)


def test_junction_refused(home, tmp_path):
    h, env = home
    target = tmp_path / "secret"
    target.mkdir()
    (target / "a.txt").write_text("x")
    _winapi.CreateJunction(str(target), str(h / "Downloads" / "link"))
    with pytest.raises(F.PathRefused, match="ссылку"):
        F.check_path(str(h / "Downloads" / "link" / "a.txt"), env=env)


# ── поиск ──
def test_find_exact_first_only_allowed_folders(home, tmp_path):
    h, env = home
    (h / "Documents" / "copy.txt").write_text("1")
    (h / "Downloads" / "my-copy.txt.bak").write_text("22")
    (h / "Desktop" / "cpu.txt").write_text("3")                 # сегодняшний случай: не должен находиться
    (tmp_path / "Windows" / "copy.txt").write_text("sys")       # вне разрешённых — не ищется
    found = F.find("copy.txt", env=env)
    assert [f["path"] for f in found] == [str(h / "Documents" / "copy.txt"), str(h / "Downloads" / "my-copy.txt.bak")]
    assert found[0]["size"] == 1
    assert all("cpu" not in f["path"] for f in found)


def test_find_in_named_folder_and_refuses_system(home, tmp_path):
    h, env = home
    lc = tmp_path / "lc"
    lc.mkdir()
    (lc / "livecheck.txt").write_text("x")
    assert F.find("livecheck.txt", str(lc), env=env)[0]["path"] == str(lc / "livecheck.txt")
    with pytest.raises(F.PathRefused):
        F.find("x", str(tmp_path / "Windows"), env=env)
    with pytest.raises(F.PathRefused):
        F.find("x", "C:\\", env=env)


def test_find_limit_three(home):
    h, env = home
    for i in range(6):
        (h / "Music" / f"song{i}.mp3").write_text("x")
    assert len(F.find("song", env=env)) == 3


# ── действия ──
def test_delete_by_name_refused_preview_then_delete_and_undelete(home, tmp_path):
    h, env = home
    f = h / "Downloads" / "copy.txt"
    f.write_text("данные")
    c = ctx(env, tmp_path)
    assert run("files.delete", "copy.txt", c, confirmed=True)["status"] == "unsupported"  # имя без пути
    assert run("files.delete", str(f), c)["detail"] == "нужно подтверждение"
    prev = run("files.delete_preview", str(f), c)
    assert prev["ok"] and str(f) in prev["detail"] and f.exists()  # предпросмотр ничего не делает
    out = run("files.delete", str(f), c, confirmed=True)
    assert out["ok"] and not f.exists() and c.platform.recycled == [str(f)]
    back = run("files.undelete", "", c)
    assert back["ok"] and f.read_text() == "данные"
    assert run("files.undelete", "", c)["status"] == "noop"  # уже возвращён


def test_undelete_only_last_24h_and_last_5(home, tmp_path):
    h, env = home
    t = [0.0]
    c = ctx(env, tmp_path, clock=lambda: t[0])
    for i in range(7):
        p = h / "Documents" / f"f{i}.txt"
        p.write_text(str(i))
        run("files.delete", str(p), c, confirmed=True)
    assert len(c.extra["journal"].recent()) == 5
    t[0] = 25 * 3600
    assert run("files.undelete", "", c)["status"] == "noop"


def test_journal_has_no_contents(home, tmp_path):
    h, env = home
    p = h / "Documents" / "secret.txt"
    p.write_text("очень личное")
    c = ctx(env, tmp_path)
    run("files.delete", str(p), c, confirmed=True)
    assert "очень личное" not in (tmp_path / "deleted.json").read_text(encoding="utf-8")


def test_copy_move_no_overwrite_no_name(home, tmp_path):
    h, env = home
    a = h / "Documents" / "a.txt"
    a.write_text("A")
    b = h / "Documents" / "b.txt"
    b.write_text("B")
    c = ctx(env, tmp_path)
    assert run("files.copy", f"a.txt|{h / 'Desktop'}", c)["status"] == "unsupported"
    assert run("files.copy", f"{a}|{b}", c)["status"] == "unsupported"  # перезапись
    assert run("files.copy", f"{a}|{h / 'Desktop'}", c)["ok"] and (h / "Desktop" / "a.txt").read_text() == "A"
    assert run("files.move", f"{a}|{tmp_path / 'Windows'}", c, confirmed=True)["status"] == "unsupported"
    assert run("files.move", f"{a}|{h / 'Pictures'}", c, confirmed=True)["ok"] and not a.exists()


def test_reveal_needs_full_path(home, tmp_path):
    h, env = home
    a = h / "Documents" / "a.txt"
    a.write_text("A")
    c = ctx(env, tmp_path)
    assert run("files.reveal", "a.txt", c)["status"] == "unsupported"
    assert run("files.reveal", str(a), c)["ok"] is True


def test_files_find_action(home, tmp_path):
    h, env = home
    (h / "Downloads" / "отчёт.pdf").write_text("x")
    out = run("files.find", "отчёт", ctx(env, tmp_path))
    assert out["ok"] and out["files"][0]["path"].endswith("отчёт.pdf")
