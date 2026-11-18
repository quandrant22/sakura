import os
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the agent package root is importable for core.hands imports.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.core import hands, kettle
from desktop.core.platform import windows as _win_platform


class TestEpicGames(unittest.TestCase):
    FORTNITE = {"DisplayName": "Fortnite", "AppName": "Fortnite", "MainGameAppName": "Fortnite", "CatalogNamespace": "fn",
                "CatalogItemId": "4fe75bbc5a674f4f9b356b5c90567da5", "bIsApplication": True}
    URI = "com.epicgames.launcher://apps/fn%3A4fe75bbc5a674f4f9b356b5c90567da5%3AFortnite?action=launch&silent=true"

    def scan(self, *items):
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for i, item in enumerate(items):
                with open(os.path.join(d, f"{i}.item"), "w", encoding="utf-8-sig") as f:
                    f.write(item if isinstance(item, str) else _json.dumps(item))
            with patch.object(hands, "_epic_manifest_dir", return_value=d):
                return hands._scan_epic()

    def test_game_launches_through_epic_launcher(self):
        self.assertEqual(self.scan(self.FORTNITE), {"fortnite": self.URI})

    def test_skips_broken_incomplete_and_dlc(self):
        apps = self.scan("не json", {**self.FORTNITE, "bIsIncompleteInstall": True},
                         {**self.FORTNITE, "DisplayName": "DLC", "AppName": "Dlc"},
                         {**self.FORTNITE, "DisplayName": "Tool", "bIsApplication": False})
        self.assertEqual(apps, {})

    def test_trademark_sign_is_removed_from_name(self):
        self.assertIn("rocket league", self.scan({**self.FORTNITE, "DisplayName": "Rocket League®"}))

    def test_no_epic_installed(self):
        with patch.object(hands, "_epic_manifest_dir", return_value="/нет/такой/папки"):
            self.assertEqual(hands._scan_epic(), {})

    def test_spoken_russian_name_finds_the_game(self):
        with patch.object(hands, "_app_cache", {"fortnite": self.URI}), patch.object(hands, "_epic_merged", True), \
             patch.object(hands, "_load_apps", return_value={}):
            self.assertEqual(hands._resolve_target("фортнайт"), self.URI)

    def test_reply_does_not_claim_the_game_is_already_open(self):
        with patch.object(hands, "_app_cache", {"fortnite": self.URI}), patch.object(hands, "_epic_merged", True), \
             patch.object(hands, "_load_apps", return_value={}), patch.object(hands, "_launch", return_value=True) as launch:
            res = hands.switch_to_app("фортнайт")
        launch.assert_called_once_with(self.URI)
        self.assertEqual(res, {"ok": True, "detail": "запускаю Fortnite через Epic Games"})


class TestHandsAppCache(unittest.TestCase):
    """Regression guards for app cache, resolve, and open_app."""

    def test_scan_apps_populates_cache(self):
        hands._app_cache = {}
        with patch.object(hands, "_scan_start_menu", return_value={}), \
             patch.object(hands, "_scan_start_apps", return_value={}), \
             patch.object(hands, "_scan_steam", return_value={"palworld": "steam://rungameid/1623730", "fallout shelter": "steam://rungameid/123"}), \
             patch.object(hands, "_scan_game_dirs", return_value={}), \
             patch.object(hands, "_load_apps", return_value={}):
            apps = hands.scan_apps(force=True)
        self.assertIn("palworld", apps)
        self.assertIn("fallout shelter", apps)
        self.assertEqual(apps["palworld"], "steam://rungameid/1623730")
        self.assertEqual(apps["fallout shelter"], "steam://rungameid/123")
        self.assertEqual(hands._app_cache, apps)

    def test_resolve_target_cyrillic(self):
        hands._app_cache = {
            "palworld": "steam://rungameid/1623730",
            "fallout shelter": "steam://rungameid/123",
        }
        self.assertEqual(hands._resolve_target("палворлд"), "steam://rungameid/1623730")
        self.assertEqual(hands._resolve_target("фоллаут шелтер"), "steam://rungameid/123")

    def test_open_app_uses_scan_when_cache_empty(self):
        hands._app_cache = {}
        with patch.object(hands, "_load_apps_cache", return_value=None), \
             patch.object(hands, "scan_apps", autospec=True) as scan, \
             patch.object(hands, "_launch", return_value=True), \
             patch.object(hands.file_index, "open", return_value=None):
            def scan_side_effect(force=False):
                hands._app_cache.update({"palworld": "steam://rungameid/1623730"})
                return hands._app_cache
            scan.side_effect = scan_side_effect
            result = hands.open_app("palworld")
        scan.assert_called_once()
        self.assertEqual(result, "открыл Palworld")

    def test_open_app_returns_real_name_not_query(self):
        """Искажённый запрос 'fall world' должен дать ответ с 'Palworld', а не 'fall world'."""
        hands._app_cache = {
            "palworld": "steam://rungameid/1623730",
        }
        with patch.object(hands, "_load_apps", return_value={}), \
             patch.object(hands, "_launch", return_value=True), \
             patch.object(hands.file_index, "open", return_value=None):
            result = hands.open_app("fall world")
        self.assertIn("Palworld", result)
        self.assertNotIn("fall world", result)
        self.assertEqual(result, "открыл Palworld")

    def test_open_app_unknown_returns_failure_without_os_startfile(self):
        hands._app_cache = {}
        with patch.object(hands, "_load_apps_cache", return_value=None), \
             patch.object(hands, "scan_apps", return_value={}), \
             patch.object(hands.file_index, "open", return_value=None), \
             patch.object(hands, "_launch", return_value=False) as launch:
            result = hands.open_app("несуществующая_хрень")
        self.assertEqual(result, "не нашла приложение 'несуществующая_хрень'")
        launch.assert_not_called()

    def test_switch_not_running_launches_once(self):
        hands._app_cache = {"discord": "C:\\Apps\\Discord\\Discord.exe"}
        launched = []
        with patch.object(hands, "_resolve_target_with_name",
                          return_value=("discord",
                                        "C:\\Apps\\Discord\\Discord.exe")), \
             patch.object(hands, "_pids_by_exe_names", return_value=set()), \
             patch.object(hands, "_launch",
                          side_effect=lambda t: launched.append(t) or True):
            result = hands.switch_to_app("дискорд")
        self.assertTrue(result["ok"])
        self.assertIn("открыла", result["detail"])
        self.assertEqual(launched, ["C:\\Apps\\Discord\\Discord.exe"])

    def test_switch_unknown_name_no_launch(self):
        with patch.object(hands, "_resolve_target_with_name",
                          return_value=None), \
             patch.object(hands, "_launch") as launch:
            result = hands.switch_to_app("несуществующая_хрень")
        self.assertFalse(result["ok"])
        launch.assert_not_called()

    def test_focus_window_is_alias(self):
        with patch.object(hands, "_resolve_target_with_name",
                          return_value=("discord", "C:\\d.exe")), \
             patch.object(hands, "_pids_by_exe_names", return_value=set()), \
             patch.object(hands, "_launch", return_value=True):
            self.assertEqual(hands.focus_window("дискорд"),
                             hands.switch_to_app("дискорд"))

    def test_execute_switch_verb(self):
        with patch.object(hands, "_resolve_target_with_name",
                          return_value=("discord", "C:\\d.exe")), \
             patch.object(hands, "_pids_by_exe_names", return_value=set()), \
             patch.object(hands, "_launch", return_value=True):
            out = hands.execute_command("switch_to_app:дискорд")
        self.assertIn("открыла", out["result"])

    def _win_env(self):
        """Мок win32-окружения: окно 100 (PID 111, заголовок Discord)."""
        import types
        state = {"visible": {100: "Discord"}, "iconic": set(),
                 "fg": 50, "order": [100]}
        gui = types.SimpleNamespace(
            IsWindowVisible=lambda h: h in state["visible"],
            GetWindowText=lambda h: state["visible"].get(h, ""),
            IsIconic=lambda h: h in state["iconic"],
            ShowWindow=lambda h, c: state["iconic"].discard(h),
            GetParent=lambda h: 0,
            GetWindowLong=lambda h, c: 4,
            BringWindowToTop=lambda h: True,
            SetForegroundWindow=lambda h: state.update(fg=h),
            EnumWindows=lambda cb, p: [cb(h, None) for h in state["order"]],
        )
        con = types.SimpleNamespace(GWL_STYLE=1, WS_POPUP=2, WS_CAPTION=4)
        return state, gui, con

    def test_switch_running_switches_without_launch(self):
        import sys
        import types
        state, gui, con = self._win_env()
        launched = []
        fake_proc = types.ModuleType("win32process")
        fake_proc.GetWindowThreadProcessId = lambda h: (0, 111)
        with patch.object(hands, "win32gui", gui), \
             patch.object(_win_platform, "win32gui", gui), \
             patch.object(hands, "win32con", con), \
             patch.dict(sys.modules, {"win32process": fake_proc}), \
             patch.object(hands, "_resolve_target_with_name",
                          return_value=("discord", "C:\\d.exe")), \
             patch.object(hands, "_pids_by_exe_names", return_value={111}), \
             patch.object(hands, "_launch",
                          side_effect=lambda t: launched.append(t) or True), \
             patch("ctypes.windll", create=True) as windll:
            windll.user32.GetForegroundWindow.side_effect = lambda: state["fg"]
            windll.user32.GetWindowThreadProcessId.return_value = 7
            windll.user32.GetCurrentThreadId.return_value = 8
            result = hands.switch_to_app("дискорд")
        self.assertTrue(result["ok"])
        self.assertIn("переключилась", result["detail"])
        self.assertEqual(launched, [])

    def test_switch_minimized_restores(self):
        import sys
        import types
        state, gui, con = self._win_env()
        state["iconic"] = {100}
        fake_proc = types.ModuleType("win32process")
        fake_proc.GetWindowThreadProcessId = lambda h: (0, 111)
        with patch.object(hands, "win32gui", gui), \
             patch.object(_win_platform, "win32gui", gui), \
             patch.object(hands, "win32con", con), \
             patch.dict(sys.modules, {"win32process": fake_proc}), \
             patch.object(hands, "_resolve_target_with_name",
                          return_value=("discord", "C:\\d.exe")), \
             patch.object(hands, "_pids_by_exe_names", return_value={111}), \
             patch("ctypes.windll", create=True) as windll:
            windll.user32.GetForegroundWindow.side_effect = lambda: state["fg"]
            windll.user32.GetWindowThreadProcessId.return_value = 7
            windll.user32.GetCurrentThreadId.return_value = 8
            result = hands.switch_to_app("дискорд")
        self.assertTrue(result["ok"])
        self.assertNotIn(100, state["iconic"])
        self.assertEqual(state["fg"], 100)

    def test_rescan_apps_command_forces_scan(self):
        with patch.object(hands, "scan_apps", autospec=True) as scan:
            result = hands.execute_command("rescan_apps")
        scan.assert_called_once_with(force=True)
        self.assertEqual(result["result"], "пересканировала приложения")

    def test_get_capabilities_does_not_raise(self):
        caps = hands.get_capabilities()
        self.assertIsInstance(caps, list)


def test_runtime_cache_and_memory_writes_use_temp_paths(tmp_path):
    apps_cache = tmp_path / "apps_cache.json"
    file_index = tmp_path / "file_index.json"
    kettle_key = tmp_path / "memory" / "kettle_key.json"

    hands._save_apps_cache({"test": "target"})
    hands.file_index._save_cache()
    kettle._save_key(b"12345678")

    assert apps_cache.exists()
    assert file_index.exists()
    assert kettle_key.exists()
