import asyncio

from sakura_core import bridge
from sakura_core.registry import validate


def test_system_volume_phrases_and_music_nudges_do_not_conflict():
    async def check():
        router = bridge.Router(declarations=bridge._declarations, llm_classify=None)
        expected = {
            "звук на пятьдесят": "50",
            "громкость 50": "50",
            "поставь звук на тридцать": "30",
        }
        for phrase, level in expected.items():
            decision = await router.route(phrase)
            assert decision.action == "system.volume"
            assert decision.param == level

        assert (await router.route("громче", "playing:music")).action == "music.volume_up"
        assert (await router.route("тише", "playing:music")).action == "music.volume_down"
        validate(bridge._declarations)

    asyncio.run(check())