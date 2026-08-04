import os
import sys
import unittest
from unittest.mock import patch

# Ensure the agent package root is importable for core.hands imports.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import hands


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
             patch.object(hands, "scan_apps", return_value={}) as scan, \
             patch.object(hands.file_index, "open", return_value=None), \
             patch.object(hands, "_launch", return_value=False) as launch:
            result = hands.open_app("несуществующая_хрень")
        self.assertEqual(result, "не нашла приложение 'несуществующая_хрень'")
        launch.assert_not_called()

    def test_rescan_apps_command_forces_scan(self):
        with patch.object(hands, "scan_apps", autospec=True) as scan:
            result = hands.execute_command("rescan_apps")
        scan.assert_called_once_with(force=True)
        self.assertEqual(result["result"], "пересканировала приложения")

    def test_get_capabilities_does_not_raise(self):
        caps = hands.get_capabilities()
        self.assertIsInstance(caps, list)
