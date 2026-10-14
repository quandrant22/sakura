"""Предохранитель раннера живой проверки: разрушительное — только в livecheck и по своим pid."""
import _winapi
import asyncio

from desktop.tools.run_action import guard, run


def test_delete_only_inside_allowed_dir(tmp_path):
    lc = tmp_path / "livecheck"
    lc.mkdir()
    allow = [str(lc)]
    assert guard("files.delete", str(lc / "copy.txt"), allow, []) is None
    assert "вне разрешённых" in guard("files.delete", str(tmp_path / "cpu.txt"), allow, [])  # случай 14.10
    assert "полный путь" in guard("files.delete", "copy.txt", allow, [])                     # имя без пути
    assert "полный путь" in guard("files.delete", str(lc) + "\\..\\cpu.txt", allow, [])       # обход через ..


def test_junction_out_of_livecheck_refused(tmp_path):
    lc = tmp_path / "livecheck"
    lc.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(lc / "link"))
    assert "вне разрешённых" in guard("files.delete", str(lc / "link" / "a.txt"), [str(lc)], [])


def test_move_both_paths_checked(tmp_path):
    lc = tmp_path / "livecheck"
    lc.mkdir()
    assert guard("files.move", f"{lc / 'a.txt'}|{lc / 'b.txt'}", [str(lc)], []) is None
    assert guard("files.move", f"{lc / 'a.txt'}|{tmp_path / 'b.txt'}", [str(lc)], []) is not None


def test_kill_only_own_pids():
    assert guard("process.kill", "4242", [], [4242]) is None
    assert guard("process.kill", "4243", [], [4242]) is not None
    assert guard("process.kill", "notepad", [], [4242]) is not None


def test_refusal_happens_before_any_connection(tmp_path):
    # нет ни ядра, ни файла токена — отказ всё равно приходит, значит, до подключения
    ev = asyncio.run(run("files.delete", "C:\\sakura-tmp\\cpu.txt", True, str(tmp_path / "нет.token"), False))
    assert ev["result"]["status"] == "refused_by_runner"


def test_other_actions_not_guarded():
    assert guard("window.list", "", [], []) is None
