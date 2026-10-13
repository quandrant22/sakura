"""Громкость приложения: сессии микшера сопоставляются с деревом процессов (Chromium audio service)."""
from desktop.core.platform.windows import pick_app_sessions

NAMES = ("яндекс", "yandex")
PROCS = {
    100: ("explorer.exe", 1),
    200: ("яндекс музыка.exe", 100),      # главный процесс — без сессии
    201: ("яндекс музыка.exe", 200),      # audio service — сессия здесь
    202: ("utility.exe", 200),            # потомок с другим именем
    300: ("opera.exe", 100),
}


def test_child_process_session_found_main_has_none():
    sessions = [(300, 1, "opera"), (201, 1, "ym-audio")]
    assert pick_app_sessions(sessions, NAMES, PROCS) == ["ym-audio"]


def test_descendant_with_other_name_and_expired_skipped_active_first():
    sessions = [(202, 0, "ym-util-inactive"), (201, 2, "ym-expired"), (201, 1, "ym-active")]
    assert pick_app_sessions(sessions, NAMES, PROCS) == ["ym-active", "ym-util-inactive"]


def test_nothing_when_no_session():
    assert pick_app_sessions([(300, 1, "opera"), (0, 1, "system")], NAMES, PROCS) == []


def test_cycle_in_parents_does_not_hang():
    procs = {1: ("a.exe", 2), 2: ("b.exe", 1)}
    assert pick_app_sessions([(1, 1, "x")], NAMES, procs) == []
