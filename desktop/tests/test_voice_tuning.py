"""Голос: перебивание «стоп», чувствительность «Сакура» по шуму, замены распознанного."""
import array
import json
import math
from types import SimpleNamespace

import pytest

from desktop.core import voice_tuning as VT

WORDS = ("сакура",)


def tone(db: float, n=1024) -> bytes:
    amp = 32768 * 10 ** (db / 20) * math.sqrt(2)
    return array.array("h", (int(amp * math.sin(i / 3)) for i in range(n))).tobytes()


def test_rms_db_and_noise_floor_ignores_speech():
    assert abs(VT.rms_db(tone(-30)) + 30) < 1.5
    assert VT.rms_db(b"\x00" * 2048) == -120.0
    nf = VT.NoiseFloor(alpha=0.2, start=-50)
    for _ in range(40):
        nf.feed(-40)  # фон стал громче
    assert -43 < nf.db < -39  # устойчивый фон поднял оценку
    before = nf.db
    nf.feed(-5)  # короткая громкая речь почти не влияет
    assert nf.db - before < 2.5


@pytest.mark.parametrize("setting,noise,mode", [("auto", -30, "low"), ("auto", -60, "high"), ("auto", -45, "normal"),
                                                ("high", -30, "high"), (None, -45, "normal")])
def test_choose_mode(setting, noise, mode):
    assert VT.choose_mode(setting, noise) == mode


def test_wake_hit_by_mode():
    assert VT.wake_hit(WORDS, "high", partial="сакураа включи") is True       # вхождение
    assert VT.wake_hit(WORDS, "normal", partial="сакураа включи") is False    # не целое слово
    assert VT.wake_hit(WORDS, "normal", partial="ну сакура включи") is True
    assert VT.wake_hit(WORDS, "low", partial="сакура") is False               # в шуме — только итог фразы
    assert VT.wake_hit(WORDS, "low", final="сакура включи свет") is True


def test_is_stop():
    assert VT.is_stop(json.dumps({"text": "сакура стоп"}, ensure_ascii=False))
    assert VT.is_stop(json.dumps({"partial": "хватит"}, ensure_ascii=False))
    assert not VT.is_stop(json.dumps({"text": "[unk]"}))
    assert not VT.is_stop("не json")


def test_replacements():
    pairs = [["вал хейм", "Valheim"], ["сакура", "Сакура"], ["", "x"], ["bad"]]
    assert VT.apply_replacements("запусти вал хейм", pairs) == "запусти Valheim"
    assert VT.apply_replacements("ВАЛ ХЕЙМ", pairs) == "Valheim"
    assert VT.apply_replacements("валхеймовский", pairs) == "валхеймовский"  # только целые слова


def test_barge_in_stops_speech_and_queue():
    from desktop.core.hearing import Hearing
    calls = []
    h = Hearing.__new__(Hearing)
    h._mute_until = 999.0
    h.agent = SimpleNamespace(player=SimpleNamespace(interrupt=lambda: calls.append("interrupt")),
                              set_state=lambda s: calls.append(("state", s)),
                              bus=SimpleNamespace(emit=lambda ev, **k: calls.append(ev)))
    h._barge_in()
    assert calls == ["interrupt", ("state", "idle"), "barge_in"] and h._mute_until == 0.0


def test_agent_applies_replacements_to_voice_only():
    from desktop.core import agent as agent_mod
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    got = []
    a.bus = SimpleNamespace(emit=lambda ev, **k: got.append(k.get("text")) if ev == "user_text" else None)
    a._set_state = lambda s: None
    a._ws = object()
    a.send_threadsafe = lambda *x, **k: None
    a.stt_replacements = [["вал хейм", "Valheim"]]
    a.submit_user_text("запусти вал хейм", source="mic")
    a.submit_user_text("запусти вал хейм", source="ui")
    assert got == ["запусти Valheim", "запусти вал хейм"]
