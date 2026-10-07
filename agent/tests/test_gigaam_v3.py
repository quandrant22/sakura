"""tests/test_gigaam_v3.py — совместимость с GigaAM v3 / gigaam 0.2.0."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

import core.hearing as H


class _FakeModel:
    """Фейковая модель GigaAM: decode(...)[0] — то, что задано."""

    def __init__(self, first):
        self.head = MagicMock()
        self.forward = MagicMock(return_value=(MagicMock(), torch.tensor([1600])))
        self.decoding = MagicMock()
        self.decoding.decode = MagicMock(return_value=[first])


def _run(model, **kw):
    audio = np.zeros(1600, dtype=np.float32)
    with patch.object(H, "torch", torch), \
         patch.object(H, "_post_process", side_effect=lambda t: t):
        return H.SpeechRecognizer._run_gigaam(None, model, audio, **kw)


@pytest.mark.parametrize("first", [
    "открой дискорд",                                # gigaam 0.1.0: строка
    ("открой дискорд", [5, 17, 3], [0, 4, 9]),       # gigaam 0.2.0: кортеж
], ids=["str-0.1.0", "tuple-0.2.0"])
def test_run_gigaam_decode_str_or_tuple(first):
    assert _run(_FakeModel(first)) == "открой дискорд"


# ── e2e: без _post_process ──────────────────────────────────────────────

def _run_with_spy(model_name, raw):
    audio = np.zeros(1600, dtype=np.float32)
    spy = MagicMock(side_effect=lambda t: "<post>" + t)
    with patch.object(H, "torch", torch), patch.object(H, "_post_process", spy):
        text = H.SpeechRecognizer._run_gigaam(None, _FakeModel(raw), audio, model_name)
    return text, spy


def test_e2e_model_skips_post_process():
    raw = ("Сакура, сделай потише на 20.", [1], [2])
    text, spy = _run_with_spy("v3_e2e_ctc", raw)
    assert text == "Сакура, сделай потише на 20."
    spy.assert_not_called()


@pytest.mark.parametrize("name", ["v2_ctc", "v3_ctc", ""])
def test_non_e2e_model_uses_post_process(name):
    text, spy = _run_with_spy(name, "открой дискорд")
    assert text == "<post>открой дискорд"
    spy.assert_called_once_with("открой дискорд")


def test_recognizer_remembers_loaded_model_name(monkeypatch):
    monkeypatch.setattr(H, "_shared_gigaam_model", None)
    monkeypatch.setattr(H, "_shared_gigaam_name", "")
    monkeypatch.setattr(H, "_GIGAAM_AVAILABLE", True)
    monkeypatch.setattr(H, "torch", torch)
    monkeypatch.setattr(H.config, "STT_ENGINE", "gigaam", raising=False)
    monkeypatch.setattr(H.config, "GIGAAM_ENABLED", True, raising=False)
    monkeypatch.setattr(H.config, "GIGAAM_MODEL", "v3_e2e_ctc", raising=False)
    monkeypatch.setattr(H, "_giga_load_model", lambda name, **kw: MagicMock())
    r = H.SpeechRecognizer()
    assert r.backend == "gigaam"
    assert r._gigaam_name == "v3_e2e_ctc"
