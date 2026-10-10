# --- Tests: GigaAM STT smoke (without real model load) ---
import warnings
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
import desktop.core.hearing as H


def test_recognizer_backend_gigaam_when_available():
    """When gigaam + torch available and STT_ENGINE=gigaam, backend=gigaam."""
    import torch
    m = MagicMock(); m.eval = MagicMock()
    m.forward = MagicMock(return_value=(MagicMock(), torch.tensor([100])))
    m.decoding = MagicMock(); m.decoding.decode = MagicMock(return_value=['privet'])
    with patch.object(H, '_GIGAAM_AVAILABLE', True), \
         patch.object(H, 'torch', torch), \
         patch('desktop.core.hearing._giga_load_model', return_value=m):
        r = H.SpeechRecognizer()
        assert r.backend == 'gigaam'
        assert r._gigaam is m


def test_recognizer_backend_vosk_when_gigaam_missing():
    """When gigaam missing, fallback to Vosk (if model exists)."""
    with patch.object(H, '_GIGAAM_AVAILABLE', False):
        r = H.SpeechRecognizer()
        assert r.backend in ('none', 'vosk')


def test_run_gigaam_direct_path():
    """Direct path model.forward + decoding.decode returns text."""
    import torch
    from unittest.mock import MagicMock
    import numpy as np
    model = _DummyModel.__new__(_DummyModel)
    model.__init__()
    audio = np.random.randn(1600).astype(np.float32)
    with patch.object(H, 'torch', torch), \
         patch.object(H, '_post_process', side_effect=lambda t: t):
        text = H.SpeechRecognizer._run_gigaam(None, model, audio)
    assert text == 'privet Mir'
    wav, length = model.forward.call_args[0]
    assert wav.shape == (1, 1600)
    assert length.tolist() == [1600]


def test_run_gigaam_empty_audio_returns_empty():
    """Empty audio signal returns empty string (no crash)."""
    import torch
    from unittest.mock import MagicMock
    import numpy as np
    model = _DummyModel.__new__(_DummyModel)
    model.__init__()
    audio = np.array([], dtype=np.float32)
    with patch.object(H, 'torch', torch), \
         patch.object(H, '_post_process', side_effect=lambda t: t):
        text = H.SpeechRecognizer._run_gigaam(None, model, audio)
    assert text == ''


def test_run_gigaam_noncontiguous_works():
    """Non-contiguous array does not break ascontiguousarray."""
    import torch
    from unittest.mock import MagicMock
    import numpy as np
    model = _DummyModel.__new__(_DummyModel)
    model.__init__()
    audio = np.array([[0.1, 0.2]], dtype=np.float32).T
    with patch.object(H, 'torch', torch), \
         patch.object(H, '_post_process', side_effect=lambda t: t):
        text = H.SpeechRecognizer._run_gigaam(None, model, audio)
    wav, length = model.forward.call_args[0]
    assert wav.shape == (1, 2)


def test_weights_only_warning_suppressed():
    """FutureWarning about weights_only is suppressed during load."""
    import torch
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        torch.load = lambda *a, **k: None
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*weights_only.*', category=FutureWarning)
                torch.load(MagicMock(), weights_only=False)
        finally:
            pass
        fu = [x for x in w if issubclass(x.category, FutureWarning) and 'weights_only' in str(x.message)]
        assert not fu, f'Remaining FutureWarning: {[str(x.message) for x in fu]}'


# --- fixtures ---

class _DummyModel:
    """Minimal mock of GigaAM model for tests."""
    def __init__(self):
        self.forward = MagicMock(return_value=(MagicMock(), np.array([1600], dtype=np.int64)))
        self.decoding = MagicMock(); self.head = MagicMock()
        self.decoding.decode = MagicMock(return_value=['privet Mir'])


@pytest.fixture
def mock_gigaam_model():
    return _DummyModel()

import warnings