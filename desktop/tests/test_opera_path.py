"""Путь к Opera GX: переменная → LOCALAPPDATA → прежний."""
import ntpath
import os

import pytest

from core import browser


@pytest.fixture(autouse=True)
def _win_join(monkeypatch):
    monkeypatch.setattr(os.path, "join", ntpath.join)


def test_env_override_wins():
    env = {"OPERA_EXE": r"D:\Opera\opera.exe", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    assert browser.find_opera_exe(env, exists=lambda p: True) == r"D:\Opera\opera.exe"


def test_localappdata_used_when_present():
    env = {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    want = r"C:\Users\x\AppData\Local\Programs\Opera GX\opera.exe"
    assert browser.find_opera_exe(env, exists=lambda p: p == want) == want


def test_missing_override_falls_through():
    env = {"OPERA_EXE": r"D:\нет\opera.exe", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    want = r"C:\Users\x\AppData\Local\Programs\Opera GX\opera.exe"
    assert browser.find_opera_exe(env, exists=lambda p: p == want) == want


def test_nothing_found_returns_first_candidate():
    env = {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    expected = r"C:\Users\x\AppData\Local\Programs\Opera GX\opera.exe"
    assert browser.find_opera_exe(env, exists=lambda p: False) == expected
    assert browser.find_opera_exe({}, exists=lambda p: False) == browser._OPERA_LEGACY
