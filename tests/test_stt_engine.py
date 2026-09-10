"""STT-движок (agent/core/hearing.py :: SpeechRecognizer).

GigaAM v2_ctc — основной STT; Vosk — фолбэк; wake-word на Vosk.
STT_ENGINE=vosk откатывает на Vosk. Тяжёлые зависимости мокаются.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_agent = os.path.join(_root, "agent")


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

# NOTE: hearing.py делает ленивый `from gigaam import load_model` ВНУТРИ
# _get_gigaam_model(), а `from vosk import ...` — на верхнем уровне.
# Поэтому мокаем ЧЕРЕЗ sys.modules ДО import/reload И дополнительно
# патчим атрибуты РЕАЛЬНЫХ пакетов с восстановлением в finally.

def _load_hearing(stt_engine="gigaam", gigaam_present=True,
                  torch_present=True, fail_giga_load=False,
                  fail_giga_run=False, vosk_model=True):
    """hearing.py с подменёнными тяжёлыми зависимостями. Возвращает (mod, state)."""
    import importlib
    import importlib.util as _ilu
    saved = dict(sys.modules)
    saved_path = list(sys.path)
    state = {"fail_load": fail_giga_load, "fail_run": fail_giga_run,
             "load_kwargs": None}
    try:
        for m in [m for m in sys.modules
                  if m == "config" or m.startswith(("core", "gigaam", "vosk",
                                                     "silero_vad", "sounddevice",
                                                     "torch", "numpy"))]:
            sys.modules.pop(m, None)
        cfg = types.ModuleType("config")
        cfg.BASE_DIR = os.path.join(_root, "agent")
        cfg.VOSK_MODEL_PATH = os.path.join(
            cfg.BASE_DIR, "vosk-model-small-ru-0.22")
        cfg.VOSK_STT_MODEL = os.path.join(
            cfg.BASE_DIR, "vosk-model-small-ru-0.22")
        cfg.VOSK_STT_RATE = 16000
        cfg.STT_ENGINE = stt_engine
        cfg.GIGAAM_MODEL = "v2_ctc"
        cfg.GIGAAM_DEVICE = "cpu"
        cfg.GIGAAM_ENABLED = True
        cfg.MIC_RATE = 16000
        cfg.MIC_BLOCK = 512
        cfg.MAX_UTTER_SEC = 60
        cfg.FOLLOWUP_SEC = 4.0
        cfg.VAD_THRESHOLD = 0.45
        cfg.VAD_END_SILENCE = 1.0
        cfg.VAD_START_TIMEOUT = 2.0
        cfg.WAKE_WORDS = ("сакура",)
        sys.modules["config"] = cfg
        fake_np = types.ModuleType("numpy")
        fake_np.float32 = "float32"
        fake_np.int16 = "int16"

        class _Arr(list):
            @property
            def size(self):
                return len(self)

            def ravel(self):
                return self

            def astype(self, *a, **k):
                if a and a[0] in ("int16", fake_np.int16):
                    return _Arr([0] * len(self))
                return self

            def tobytes(self):
                return b"\x00" * (len(self) * 2)

            def __mul__(self, k):
                return _Arr([x * k for x in self])

            __rmul__ = __mul__

        fake_np.ascontiguousarray = (
            lambda a, dtype=None: a if isinstance(a, _Arr) else _Arr(list(a)))
        fake_np.frombuffer = lambda b, dtype=None: _Arr([0.0] * 1600)
        sys.modules["numpy"] = fake_np
        if torch_present:
            fake_torch = types.ModuleType("torch")
            fake_torch.set_num_threads = lambda *a, **k: None

            class _T:
                def __init__(self, data=None):
                    self.shape = (1, len(data) if data else 0)

                def unsqueeze(self, dim):
                    return self

            fake_torch.from_numpy = lambda a: _T(list(a))
            fake_torch.tensor = lambda d: _T(d)
            fake_torch.inference_mode = lambda: _NullCtx()
            fake_torch.load = lambda *a, **k: object()
            sys.modules["torch"] = fake_torch

        class _Decoding:
            def decode(self, head, enc, enc_len):
                if state["fail_run"]:
                    raise RuntimeError("giga boom")
                return ["открой дискорд"]

        class _FakeGigaModel:
            def __init__(self):
                self.head = object()
                self.decoding = _Decoding()

            def forward(self, wav, length):
                if state["fail_run"]:
                    raise RuntimeError("giga boom")
                return object(), object()

            def eval(self):
                return self

        def _fake_load(model_name, device="cpu", **kw):
            state["load_kwargs"] = {"model": model_name,
                                    "device": device, **kw}
            if state["fail_load"]:
                raise RuntimeError("no giga model")
            return _FakeGigaModel()

        # PART2-MARKER
        if gigaam_present:
            gigaam_mod = types.ModuleType("gigaam")
            gigaam_mod.load_model = _fake_load
            sys.modules["gigaam"] = gigaam_mod
        try:
            import gigaam as _real_giga
            state["_real_giga_orig"] = _real_giga.load_model
            if gigaam_present:
                _real_giga.load_model = _fake_load
            else:
                def _missing(*a, **k):
                    raise ImportError("gigaam not installed (mock)")
                _real_giga.load_model = _missing
            state["_real_giga"] = _real_giga
        except Exception:
            pass
        # Точка подмены: hearing резолвит загрузчик через
        # hearing._giga_load_model — патчим АТРИБУТ МОДУЛЯ после reload
        # (см. ниже, _fake_loader определён после reload).

        class _FakeVoskModel:
            def __init__(self, path):
                self.path = path

        class _FakeRec:
            def __init__(self, model, rate):
                self.rate = rate

            def SetWords(self, v):
                pass

            def AcceptWaveform(self, chunk):
                return True

            def Result(self):
                return '{"text": "открой дискорд"}'

            def FinalResult(self):
                return '{"text": "открой дискорд"}'

            def PartialResult(self):
                return '{"partial": ""}'

        vosk_mod = types.ModuleType("vosk")
        vosk_mod.Model = _FakeVoskModel if vosk_model else None
        vosk_mod.KaldiRecognizer = _FakeRec
        sys.modules["vosk"] = vosk_mod
        # hearing держит ИМПОРТИРОВАННЫЕ НА ВЕРХНЕМ УРОВНЕ ссылки
        # VoskModel/KaldiRecognizer — подменяем ИХ напрямую после reload
        # (см. ниже).
        try:
            import vosk as _real_vosk
            state["_real_vosk_orig"] = (_real_vosk.Model,
                                        _real_vosk.KaldiRecognizer)
            _real_vosk.Model = _FakeVoskModel if vosk_model else None
            _real_vosk.KaldiRecognizer = _FakeRec
        except Exception:
            pass
        sys.modules["sounddevice"] = types.ModuleType("sounddevice")
        silero_mod = types.ModuleType("silero_vad")
        silero_mod.load_silero_vad = lambda *a, **k: object()
        sys.modules["silero_vad"] = silero_mod
        # PART3-MARKER
        real_find_spec = _ilu.find_spec

        def _patched_find_spec(name, *a, **k):
            if name == "gigaam" and not gigaam_present:
                return None
            return real_find_spec(name, *a, **k)

        with patch.object(_ilu, "find_spec", _patched_find_spec):
            if _agent not in sys.path:
                sys.path.insert(0, _agent)
            hearing = importlib.import_module("core.hearing")
            importlib.reload(hearing)

        def _fake_loader(model_name, device="cpu", **kw):
            state["load_kwargs"] = {"model": model_name,
                                    "device": device, **kw}
            if state["fail_load"]:
                raise RuntimeError("no giga model")
            return _FakeGigaModel()

        hearing._giga_load_model = _fake_loader
        # STT-фолбэк в тестах НЕ должен зависеть от наличия/отсутствия
        # реальных Vosk-моделей в окружении (чистый клон ≠ машина Мастера):
        # подменяем загрузчик общей модели фейковой Vosk-моделью.
        if vosk_model:
            hearing._get_shared_model = lambda kind="wake": _FakeVoskModel(
                os.path.join(cfg.BASE_DIR, "vosk-model-small-ru-0.22"))
        else:
            hearing._get_shared_model = lambda kind="wake": None
        # Верхнеуровневые `from vosk import Model as VoskModel,
        # KaldiRecognizer` уже связаны в модуле — подменяем напрямую.
        hearing.VoskModel = _FakeVoskModel if vosk_model else None
        hearing.KaldiRecognizer = _FakeRec
        hearing._shared_gigaam_model = None
        hearing._shared_vosk_model_wake = None
        hearing._shared_vosk_model_stt = None
        hearing._GIGAAM_AVAILABLE = bool(gigaam_present)
        return hearing, state
    finally:
        try:
            _rg = state.get("_real_giga")
            if _rg is not None and "_real_giga_orig" in state:
                _rg.load_model = state["_real_giga_orig"]
        except Exception:
            pass
        try:
            import vosk as _real_vosk2
            if "_real_vosk_orig" in state:
                _real_vosk2.Model = state["_real_vosk_orig"][0]
                _real_vosk2.KaldiRecognizer = state["_real_vosk_orig"][1]
        except Exception:
            pass
        for m in [m for m in list(sys.modules)
                  if m == "config" or m.startswith(("core", "gigaam", "vosk",
                                                     "silero_vad", "sounddevice",
                                                     "torch", "numpy"))]:
            sys.modules.pop(m, None)
        for m, v in saved.items():
            sys.modules[m] = v
        sys.path[:] = saved_path


def _audio(n=1600):
    import numpy as _np
    try:
        return _np.array([0.01] * n, dtype=_np.float32)
    except Exception:
        return [0.01] * n


class TestGigaAMPrimary(unittest.TestCase):
    def test_gigaam_is_default_backend(self):
        hearing, _ = _load_hearing()
        self.assertEqual(hearing.SpeechRecognizer().backend, "gigaam")

    def test_gigaam_transcribe_contract(self):
        hearing, state = _load_hearing()
        text = hearing.SpeechRecognizer().transcribe(_audio())
        self.assertIn("дискорд", text.lower())
        self.assertEqual(state["load_kwargs"]["device"], "cpu")
        self.assertFalse(state["load_kwargs"].get("fp16_encoder", True))
        self.assertEqual(state["load_kwargs"]["model"], "v2_ctc")

    def test_gigaam_model_loaded_once(self):
        hearing, _ = _load_hearing()
        self.assertIs(hearing._get_gigaam_model(), hearing._get_gigaam_model())

    def test_gigaam_device_forced_cpu(self):
        hearing, _ = _load_hearing()
        self.assertEqual(hearing._gigaam_device(), "cpu")


class TestVoskFallback(unittest.TestCase):
    def test_fallback_when_gigaam_missing(self):
        hearing, _ = _load_hearing(gigaam_present=False)
        r = hearing.SpeechRecognizer()
        self.assertEqual(r.backend, "vosk")
        self.assertIn("дискорд", r.transcribe(_audio()).lower())

    def test_fallback_when_gigaam_load_fails(self):
        hearing, _ = _load_hearing(fail_giga_load=True)
        r = hearing.SpeechRecognizer()
        self.assertEqual(r.backend, "vosk")
        self.assertIn("дискорд", r.transcribe(_audio()).lower())

    def test_fallback_when_gigaam_run_fails(self):
        hearing, _ = _load_hearing(fail_giga_run=True)
        r = hearing.SpeechRecognizer()
        self.assertEqual(r.backend, "gigaam")
        with self.assertLogs("sakura.hearing", level="WARNING") as cm:
            text = r.transcribe(_audio())
        self.assertIn("дискорд", text.lower())
        self.assertTrue(any("фолбэк" in m for m in cm.output),
                        f"нет явного warning: {cm.output}")

    def test_explicit_warning_when_gigaam_missing(self):
        with self.assertLogs("sakura.hearing", level="INFO") as cm:
            hearing, _ = _load_hearing(gigaam_present=False)
            hearing.SpeechRecognizer()
        out = "\n".join(cm.output).lower()
        self.assertIn("gigaam", out)
        self.assertIn("vosk", out)


class TestEngineSwitch(unittest.TestCase):
    def test_stt_engine_vosk(self):
        hearing, state = _load_hearing(stt_engine="vosk")
        self.assertFalse(hearing._gigaam_wanted())
        r = hearing.SpeechRecognizer()
        self.assertEqual(r.backend, "vosk")
        self.assertIsNone(r._gigaam)
        self.assertIsNone(state["load_kwargs"])
        self.assertIn("дискорд", r.transcribe(_audio()).lower())

    def test_stt_engine_gigaam(self):
        hearing, _ = _load_hearing(stt_engine="gigaam")
        self.assertTrue(hearing._gigaam_wanted())


class TestWakeWordUntouched(unittest.TestCase):
    def test_wake_model_loader_still_vosk(self):
        import inspect
        hearing, _ = _load_hearing()
        src = inspect.getsource(hearing._get_shared_model)
        self.assertIn("VoskModel", src)
        self.assertNotIn("giga", src.lower())
        run_src = inspect.getsource(hearing.Hearing.run)
        self.assertIn("KaldiRecognizer", run_src)
        self.assertIn('_get_shared_model("wake")', run_src)
        self.assertNotIn("_gigaam", run_src)
        self.assertNotIn("GigaAM", run_src)


class TestPostProcessKept(unittest.TestCase):
    def test_gigaam_lowercase_gets_punctuation(self):
        hearing, _ = _load_hearing()
        out = hearing._post_process("открой дискорд")
        self.assertTrue(out[0].isupper())
        self.assertTrue(out.endswith((".", "?", "!")))


if __name__ == "__main__":
    unittest.main()
