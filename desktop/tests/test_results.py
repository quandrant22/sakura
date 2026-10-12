"""Контракт результата команды: ok=true только при status=done."""
import pytest

from desktop.core import results as r


@pytest.mark.parametrize("text,status", [
    ("громкость 70%", "done"),
    ("открыл Telegram", "done"),
    ("запустила игру", "done"),             # «пуст» внутри «запустила» — не неудача
    ("Нет активного плеера", "noop"),
    ("Ничего не играет", "noop"),
    ("Opera не найдена", "failed"),
    ("расширение не выполнило tab_new: timeout", "failed"),
    ("не нашла приложение 'x'", "failed"),
    ("app_not_found:steam", "failed"),
    ("file_not_found:отчёт", "failed"),
    ("неизвестная команда: foo", "unsupported"),
    ("расширение не подключено", "unsupported"),
    ("громкость недоступна: x", "unsupported"),
    ("", "failed"),
    (None, "failed"),
])
def test_classify_legacy_text(text, status):
    out = r.from_legacy(text)
    assert out["status"] == status
    assert out["ok"] is (status == "done")


def test_dict_ok_false_never_done():
    out = r.from_legacy({"ok": False, "result": "лайк"})
    assert out == {"ok": False, "status": "failed", "detail": "лайк"}
    assert r.from_legacy({"ok": True, "result": "Нет активного плеера"})["status"] == "noop"
    assert r.from_legacy({"ok": True, "result": "следующий"})["ok"] is True
    assert r.from_legacy({"error": "timeout"})["ok"] is False


def test_explicit_status_kept():
    assert r.from_legacy(r.unsupported("нужно расширение")) == {
        "ok": False, "status": "unsupported", "detail": "нужно расширение"}
    with pytest.raises(ValueError):
        r.result("maybe", "x")
