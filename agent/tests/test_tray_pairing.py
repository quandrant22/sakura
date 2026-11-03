"""Пункты трея «Спарить с сервером…» / «Сбросить спаривание» (ТЗ-4)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qtw = pytest.importorskip("PyQt6.QtWidgets")

from ui import app as ui_app


class _Bus:
    def subscribe(self, fn):
        self.fn = fn


class _Agent:
    def __init__(self):
        self.calls = []

    async def pair_device(self, code):
        return "Спарено"

    async def reset_pairing(self):
        return "Спаривание сброшено"

    def run_in_loop(self, fn, *args, done=None):
        self.calls.append((fn.__name__, args))
        return True


@pytest.fixture(scope="module")
def qapp():
    return qtw.QApplication.instance() or qtw.QApplication([])


_keep = []


def _menu(qapp, agent):
    menu = qtw.QMenu()
    bridge = ui_app.UiBridge(_Bus())
    ui_app.add_pairing_actions(menu, qapp, agent, bridge, tray=None)
    _keep.append((menu, bridge))           # иначе Qt удалит меню вместе с действиями
    return {a.text(): a for a in menu.actions()}, bridge


def test_actions_present_and_pair_passes_code(qapp, monkeypatch):
    agent = _Agent()
    actions, _ = _menu(qapp, agent)
    assert {"Спарить с сервером…", "Сбросить спаривание"} <= set(actions)
    seen = {}

    def get_text(parent, title, label, mode):
        seen["mode"] = mode
        return "  слова  ", True

    monkeypatch.setattr(qtw.QInputDialog, "getText", staticmethod(get_text))
    actions["Спарить с сервером…"].trigger()
    assert seen["mode"] == qtw.QLineEdit.EchoMode.Password       # ввод скрыт
    assert agent.calls == [("pair_device", ("  слова  ",))]


def test_cancelled_dialog_does_nothing(qapp, monkeypatch):
    agent = _Agent()
    actions, _ = _menu(qapp, agent)
    monkeypatch.setattr(qtw.QInputDialog, "getText", staticmethod(lambda *a: ("x", False)))
    actions["Спарить с сервером…"].trigger()
    assert agent.calls == []


def test_reset_asks_confirmation(qapp, monkeypatch):
    agent = _Agent()
    actions, _ = _menu(qapp, agent)
    monkeypatch.setattr(qtw.QMessageBox, "question",
                        staticmethod(lambda *a: qtw.QMessageBox.StandardButton.No))
    actions["Сбросить спаривание"].trigger()
    assert agent.calls == []
    monkeypatch.setattr(qtw.QMessageBox, "question",
                        staticmethod(lambda *a: qtw.QMessageBox.StandardButton.Yes))
    actions["Сбросить спаривание"].trigger()
    assert agent.calls == [("reset_pairing", ())]
