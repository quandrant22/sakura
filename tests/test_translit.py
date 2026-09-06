"""
Тесты ЕДИНОЙ нормализации названий (modules/translit.py):
  - транслит/фонетика: «палворлд» ≡ Palworld, «фоллаут шелтер» ≡ Fallout Shelter;
  - search_game() находит игры по кириллице (баг: до этого — None);
  - агент (agent/core/hands.py) использует ту же реализацию (паритет).
"""
import os
import sys
import unittest
from unittest.mock import patch

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


class TestTranslitUnit(unittest.TestCase):

    def test_transliterate_combinations_and_letters(self):
        from modules.translit import transliterate
        self.assertEqual(transliterate("палворлд"), "palvorld")
        self.assertEqual(transliterate("джетсет радио"), "jetset radio")
        self.assertEqual(transliterate("remnant"), "remnant")  # латиница как есть

    def test_phonetic_normalize(self):
        from modules.translit import phonetic_normalize
        self.assertEqual(phonetic_normalize("palworld"), "palvarld")
        self.assertEqual(phonetic_normalize("fallout"), "falaut")
        self.assertEqual(phonetic_normalize("phantom"), "fantam")
        self.assertEqual(phonetic_normalize("duck"), "duk")
        self.assertEqual(phonetic_normalize("boss"), "bas")

    def test_normalize_name_cyrillic_equals_latin(self):
        from modules.translit import normalize_name
        self.assertEqual(normalize_name("палворлд"),
                         normalize_name("Palworld"))
        self.assertEqual(normalize_name("фоллаут шелтер"),
                         normalize_name("Fallout Shelter"))
        self.assertEqual(normalize_name("Remnant: From the Ashes"),
                         "remnantframtheashes")

    def test_content_tokens_drop_stopwords(self):
        from modules.translit import content_tokens
        # артикли/предлоги игнорируются: «ремнант фром зе эйс» = «remnant from the ashes»
        self.assertEqual(content_tokens("Remnant: From the Ashes"),
                         ["remnant", "ashes"])
        self.assertEqual(content_tokens("ремнант фром зе эйс"),
                         ["remnant", "eys"])
        self.assertEqual(content_tokens("Fallout Shelter"),
                         ["falaut", "shelter"])


class TestSearchGameCyrillic(unittest.TestCase):
    """Баг-репродукция: search_game() не находил игры по кириллице."""

    LIB = [
        {"appid": 1, "name": "Remnant: From the Ashes", "playtime_forever": 100},
        {"appid": 2, "name": "Palworld", "playtime_forever": 90},
        {"appid": 3, "name": "Fallout Shelter", "playtime_forever": 80},
        {"appid": 4, "name": "Hollow Knight", "playtime_forever": 70},
        {"appid": 5, "name": "ELDEN RING", "playtime_forever": 60},
    ]

    def _search(self, q):
        from modules import steam_integration as si
        with patch.object(si, "_library", list(self.LIB)):
            return si.search_game(q)

    def test_latin_regressions(self):
        # прежнее поведение не сломано
        self.assertEqual(self._search("remnant")["name"],
                         "Remnant: From the Ashes")
        self.assertEqual(self._search("Remnant: From the Ashes")["name"],
                         "Remnant: From the Ashes")
        self.assertEqual(self._search("elden")["name"], "ELDEN RING")

    def test_cyrillic_queries(self):
        self.assertEqual(self._search("ремнант")["name"],
                         "Remnant: From the Ashes")
        self.assertEqual(self._search("ремнант фром зе эйс")["name"],
                         "Remnant: From the Ashes")
        self.assertEqual(self._search("палворлд")["name"], "Palworld")
        self.assertEqual(self._search("фоллаут шелтер")["name"],
                         "Fallout Shelter")

    def test_not_found_is_none(self):
        self.assertIsNone(self._search("несуществующая игра"))
        self.assertIsNone(self._search(""))
        self.assertIsNone(self._search("   "))

    def test_empty_library(self):
        from modules import steam_integration as si
        with patch.object(si, "_library", []):
            self.assertIsNone(si.search_game("ремнант"))



class TestHandsNormalizationParity(unittest.TestCase):
    """Агент и сервер используют ОДНУ нормализацию (или синхронную копию)."""

    @classmethod
    def setUpClass(cls):
        # Импортируем hands ТАК ЖЕ, как на ноутбуке: `from core.hands import ...`
        # при agent/ в начале sys.path (тогда `import config` внутри hands
        # резолвится в агентный config.py с APPS_FILE).
        # После импорта полностью восстанавливаем окружение процесса,
        # чтобы не повлиять на остальные тесты.
        _agent = os.path.join(_root, "agent")
        cls._import_error = None
        saved_path = list(sys.path)
        saved_config = sys.modules.pop("config", None)  # иначе hands увидит кэш корневого config
        saved_modules = {k: v for k, v in sys.modules.items()
                         if k == "core" or k.startswith("core.")}
        if _agent not in sys.path:
            sys.path.insert(0, _agent)
        try:
            from core import hands
            cls.hands = hands
        except Exception as e:
            cls.hands = None
            cls._import_error = e
        finally:
            sys.path[:] = saved_path
            # config: вернуть корневой (агентный больше не нужен процессу)
            if saved_config is not None:
                sys.modules["config"] = saved_config
            else:
                sys.modules.pop("config", None)
            for k in list(sys.modules):
                if k == "core" or k.startswith("core."):
                    if k not in saved_modules:
                        sys.modules.pop(k, None)

    CORPUS = [
        "Палворлд", "палворлд", "Remnant: From the Ashes",
        "ремнант фром зе эйс", "фоллаут шелтер", "Fallout Shelter",
        "Hollow Knight", "ХОЛЛОУ НАЙТ", "Grand Theft Auto V", "",
        "Steam", "стим",
    ]

    def _require_hands(self):
        if self.hands is None:
            self.skipTest(f"core.hands недоступен: {self._import_error}")

    def test_parity_with_shared_module(self):
        self._require_hands()
        from modules import translit
        for s in self.CORPUS:
            self.assertEqual(self.hands._transliterate(s),
                             translit.transliterate(s), s)
            self.assertEqual(self.hands._phonetic_normalize(s),
                             translit.phonetic_normalize(s), s)
            self.assertEqual(self.hands._normalize_app_name(s),
                             translit.normalize_name(s), s)
            self.assertEqual(self.hands._normalize_app_name_tokens(s),
                             translit.normalize_tokens(s), s)

    def test_hands_uses_shared_module(self):
        """В обычном рантайме (репозиторий целиком) агент импортирует
        общий modules.translit — одна реализация, не копия."""
        self._require_hands()
        self.assertEqual(self.hands._NORMALIZATION_SOURCE, "modules.translit")
        from modules.translit import transliterate
        # функции — буквально ОДИН и тот же код
        self.assertIs(self.hands._transliterate, transliterate)


if __name__ == "__main__":
    unittest.main()
