"""«стоп» чтения (sakura_core/tts_control.is_tts_stop) и остановка задачи браузера.

Голосовой/текстовый ход (adapters/ws.py) и Telegram завершают ход, если
is_tts_stop — до реестра. «стоп задача», «стоп браузер», «хватит в браузере» —
триггеры browser.stop: раньше их глотала проверка «стоп» в любом месте фразы.

Run: python -m pytest tests/test_tts_stop.py -q
"""

import pytest

from sakura_core.tts_control import is_tts_stop


@pytest.mark.parametrize("text", ["стоп", "Стоп.", "хватит", "достаточно", "хватит читать",
                                  "останови чтение", "перестань читать", "стоп, хватит",
                                  "стоп музыку"])
def test_reading_stop_phrases(text):
    assert is_tts_stop(text) is True


@pytest.mark.parametrize("text", ["стоп задача", "Стоп задача!", "стоп задачу", "стоп браузер",
                                  "хватит в браузере", "останови задачу", "отмени задачу"])
def test_browser_task_stop_is_not_reading_stop(text):
    assert is_tts_stop(text) is False


def test_task_stop_phrases_reach_browser_stop(monkeypatch):
    """Фразы, которые is_tts_stop больше не глотает, роутятся в browser.stop."""
    import asyncio

    import config
    import sakura_core.bridge as br
    from sakura_core.registry import load
    from sakura_core.router import Router

    async def no_llm(text, catalog):
        return None

    monkeypatch.setattr(config, "BROWSER_AGENT", True)
    router = Router(declarations=br._gate(load()), llm_classify=no_llm)
    for phrase in ("стоп задача", "стоп браузер", "хватит в браузере"):
        assert asyncio.run(router.route(phrase, None, source="pc")).action == "browser.stop"
