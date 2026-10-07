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
