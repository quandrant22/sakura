"""core/hearing.py — слух.

Архитектура:
  - Vosk ловит wake word «Сакура»
  - Silero VAD определяет начало/конец речи
  - Vosk распознаёт фразу (русская модель 0.42)
  - Анализ просодии голоса (энергия/темп → mood_vector)
  - Голосовые закладки («запомни это» → память без VPS-вызова)
"""

import gc
import json
import logging
import os
import re
import threading
import time

import config

try:    import sounddevice as sd
except ImportError: sd = None
try:    import numpy as np
except ImportError: np = None
try:    import torch; torch.set_num_threads(1)
except ImportError: torch = None
try:    from vosk import Model as VoskModel, KaldiRecognizer
except ImportError: VoskModel = KaldiRecognizer = None
try:    from silero_vad import load_silero_vad
except ImportError: load_silero_vad = None

log = logging.getLogger("sakura.hearing")

logging.getLogger("httpx").setLevel(logging.WARNING)

_TTS_TAIL = 0.4

_BOOKMARK_RE = re.compile(
    r"сакура[,\s]*|запомни это[,\s]*|сохрани это[,\s]*|заметь это[,\s]*|в память[,\s]*",
    re.IGNORECASE,
)
_BOOKMARK_KW = ("запомни это", "сохрани это", "заметь это", "в память")


def _enable_cuda_libs():
    if os.name != "nt":
        return
    import site
    roots = list(site.getsitepackages())
    user  = site.getusersitepackages()
    if user:
        roots.append(user)
    for base in roots:
        for lib in ("cublas", "cudnn"):
            path = os.path.join(base, "nvidia", lib, "bin")
            if os.path.isdir(path):
                try:
                    os.add_dll_directory(path)
                except OSError:
                    pass


class SileroVAD:
    SR    = 16000
    FRAME = 512

    def __init__(self):
        self._model = load_silero_vad()

    def speech_prob(self, pcm16: bytes) -> float:
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) != self.FRAME:
            return 0.0
        return self._model(torch.from_numpy(audio), self.SR).item()

    def reset(self):
        self._model.reset_states()


# ── Определение вопроса (Vosk很少 ставит «?») ────────────────────────

# Вопросительные слова в начале фразы
_Q_FIRST = (
    "что", "чё", "чо", "как", "какой", "какая", "какое", "какие", "каков",
    "который", "которая", "которое", "во сколько",
    "где", "куда", "откуда", "когда", "почему", "зачем", "отчего",
    "кто", "кого", "кому", "чей", "чья", "чьё", "сколько", "насколько",
    "разве", "неужели", "правда", "правда ли", "можешь", "можно",
    "а что", "а как", "а где", "а когда", "а кто", "а сколько", "а почему",
)
# Вопросительные обороты в любом месте
_Q_ANY = (
    "можешь ли", "можно ли", "не так ли", "не правда ли",
    "что думаешь", "как думаешь", "как считаешь", "что скажешь",
    "согласна", "знаешь ли", "помнишь ли",
)


def _normalize_question(text: str) -> str:
    """
    Vosk很少 ставит «?». Определяем вопрос по вопросительным
    словам и дописываем «?», чтобы дальше его правильно разграничивали.
    """
    if not text:
        return text
    t = text.strip()
    if t.endswith("?"):
        return t

    low = t.lower().lstrip("аи, ")  # «а что...», «и где...»
    first_word = low.split()[0] if low.split() else ""

    is_question = (
        first_word in _Q_FIRST
        or any(low.startswith(q + " ") or low == q for q in _Q_FIRST)
        or any(q in low for q in _Q_ANY)
    )

    if is_question:
        # Убираем точку в конце если есть, ставим «?»
        t = t.rstrip(" .…")
        return t + "?"
    return t


class SpeechRecognizer:
    """Vosk-based STT — быстрый, лёгкий, точный для русского."""

    def __init__(self):
        self._model   = None
        self._lock    = threading.Lock()
        self._model   = self._build()  # Предзагрузка при старте

    def transcribe(self, audio) -> str:
        """Принимает numpy array float32, возвращает строку."""
        if self._model is None:
            return ""
        with self._lock:
            try:
                text = self._run(self._model, audio)
            except Exception as e:
                log.error(f"Vosk STT ошибка: {e}")
                return ""
        return text

    def _build(self):
        """Загружает Vosk модель для STT."""
        model_path = os.path.join(config.BASE_DIR, config.VOSK_STT_MODEL)
        if not os.path.isdir(model_path):
            log.warning(f"Модель Vosk STT не найдена: {model_path}")
            log.warning(f"Скачай: https://alphacephei.com/vosk/models → {config.VOSK_STT_MODEL}")
            return None

        try:
            from vosk import Model as VoskModel
            log.info(f"[STT] Загружаю Vosk модель: {config.VOSK_STT_MODEL}...")
            model = VoskModel(model_path)
            log.info(f"[STT] Vosk модель загружена: {config.VOSK_STT_MODEL}")
            return model
        except Exception as e:
            log.error(f"Ошибка загрузки Vosk STT: {e}")
            return None

    def _run(self, model, audio) -> str:
        """Распознаёт аудио через Vosk с пост-обработкой."""
        from vosk import KaldiRecognizer

        # Конвертируем float32 → int16
        import numpy as np
        audio_int16 = (audio * 32768).astype(np.int16).tobytes()

        rec = KaldiRecognizer(model, config.VOSK_STT_RATE)
        rec.SetWords(True)

        # Разбиваем на блоки по 4000 сэмплов (250мс) для потоковой обработки
        chunk_size = 4000 * 2  # int16 = 2 байта на сэмпл
        for i in range(0, len(audio_int16), chunk_size):
            chunk = audio_int16[i:i + chunk_size]
            rec.AcceptWaveform(chunk)

        result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip()

        # Пост-обработка
        text = _post_process(text)
        return text

    def _unload(self):
        """Выгрузка модели (не нужна для Vosk — модель лёгкая)."""
        pass


# ── Пост-обработка текста Vosk ──────────────────────────────────────

# Вопросительные слова
_Q_WORDS = (
    "что", "чё", "чо", "как", "какой", "какая", "какое", "какие",
    "где", "куда", "откуда", "когда", "почему", "зачем", "отчего",
    "кто", "кого", "кому", "чей", "чья", "чьё", "сколько", "насколько",
    "можно", "можешь", "разве", "неужели", "правда",
)

# Стоп-слова для разделения предложений
_SPLITTERS = (
    "и", "а", "но", "или", "что", "как", "где", "когда", "потому",
    "поэтому", "тоже", "также", "кроме", "помимо", "однако",
)

# Слова которые точно начинают предложение
_SENTENCE_STARTERS = (
    "привет", "здравствуй", "добрый", "доброе", "доброе утро", "добрый вечер",
    "слушай", "смотрите", "кстати", "пошли", "давай", "ладно",
    "хорошо", "плохо", "отлично", "прекрасно",
)

# Слова которые не нужно капитализировать (служебные)
_LOWERCASE_WORDS = (
    "и", "а", "но", "в", "на", "с", "к", "по", "для", "из", "за", "о", "у",
    "не", "ни", "да", "нет", "уже", "ещё", "еще", "вот", "тут", "там",
)


def _post_process(text: str) -> str:
    """
    Пост-обработка текста от Vosk:
    1. Капитализация первых букв предложений
    2. Добавление пунктуации
    3. Исправление типичных ошибок
    """
    if not text or len(text) < 2:
        return text

    # Разбиваем на слова
    words = text.split()
    if not words:
        return text

    # 1. Капитализация
    result = _capitalize_text(words)

    # 2. Пунктуация
    result = _add_smart_punctuation(result)

    # 3. Исправление типичных ошибок Vosk
    result = _fix_common_errors(result)

    return result


def _capitalize_text(words: list) -> str:
    """Капитализация первых букв предложений."""
    if not words:
        return ""

    result = []
    capitalize_next = True  # Первое слово всегда с заглавной

    for i, word in enumerate(words):
        if capitalize_next and word and word[0].isalpha():
            word = word[0].upper() + word[1:]
            capitalize_next = False

        result.append(word)

        # Следующее слово будет с заглавной если:
        # - Текущее заканчивается на "." или "!"
        # - Текущее — разделитель в начале фразы
        if word.endswith((".", "!", "?")):
            capitalize_next = True
        elif word.lower() in _SPLITTERS and i > 0:
            # Проверяем длину текущей фразы
            phrase_len = sum(len(w) for w in result[-5:])
            if phrase_len > 30:
                capitalize_next = True

    return " ".join(result)


def _add_smart_punctuation(text: str) -> str:
    """Добавляет пунктуацию на основе анализа слов."""
    if not text:
        return text

    # Если уже есть знаки препинания — не трогаем
    if any(c in text for c in ".!?"):
        return text

    words = text.split()
    if len(words) < 2:
        return text + "."

    # Проверяем — есть ли вопросительное слово?
    has_question = any(w.lower().rstrip(",.") in _Q_WORDS for w in words)

    if has_question:
        return text + "?"

    return text + "."


def _fix_common_errors(text: str) -> str:
    """Исправляет типичные ошибки Vosk."""
    # Исправляем "как бы" → "как бы" (оставляем как есть)
    # Исправляем "ну" в начале
    # Исправляем "эээ" → убираем

    # Убираем повторяющиеся слова
    import re
    text = re.sub(r'\b(\w+)\s+\1\b', r'\1', text)

    # Убираем "эээ", "ммм" и т.д.
    text = re.sub(r'\b[ээммм]+\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _normalize_question(text: str) -> str:
    """
    Vosk很少 ставит «?». Определяем вопрос по вопросительным
    словам и дописываем «?», чтобы дальше его правильно разграничивали.
    """
    if not text:
        return text
    t = text.strip()
    if t.endswith("?"):
        return t

    low = t.lower().lstrip("аи, ")  # «а что...», «и где...»
    first_word = low.split()[0] if low.split() else ""

    is_question = (
        first_word in _Q_WORDS
        or any(low.startswith(q + " ") or low == q for q in _Q_WORDS)
        or any(q in low for q in _Q_WORDS)
    )

    if is_question:
        t = t.rstrip(" .…")
        return t + "?"
    return t


# ── Анализ просодии (Фаза 5) ─────────────────────────────────────────

def analyze_voice_emotion(pcm_bytes: bytes, sample_rate: int = 16000) -> dict:
    """Быстрый анализ энергии и темпа голоса без внешних библиотек."""
    if not np or not pcm_bytes:
        return {"label": "neutral", "valence_hint": 0.0, "arousal_hint": 0.0}
    audio  = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    dur    = len(audio) / sample_rate
    if dur < 0.1:
        return {"label": "neutral", "valence_hint": 0.0, "arousal_hint": 0.0}
    rms    = float(np.sqrt(np.mean(audio ** 2)))
    energy = min(1.0, rms * 10)
    zcr    = float(np.mean(np.abs(np.diff(np.sign(audio)))) / 2)
    tempo  = min(2.0, zcr / 0.08)
    if energy > 0.65 and tempo > 1.3:
        label, av, aa = "excited", +0.05, +0.15
    elif energy > 0.70 and tempo < 0.8:
        label, av, aa = "angry",   -0.20, +0.18
    elif energy < 0.25 and tempo < 0.7:
        label, av, aa = "tired",   -0.08, -0.15
    elif energy < 0.30:
        label, av, aa = "calm",    +0.05, -0.08
    else:
        label, av, aa = "neutral",  0.0,   0.0
    return {"label": label, "valence_hint": av, "arousal_hint": aa}


def apply_voice_emotion(prosody: dict):
    if prosody["label"] == "neutral":
        return
    try:
        from modules.mood_vector import set_target, get_current
        cur = get_current()
        set_target(cur["valence"] + prosody["valence_hint"],
                   cur["arousal"] + prosody["arousal_hint"],
                   blend=0.20)
    except Exception:
        pass


# ── Основной класс ────────────────────────────────────────────────────

class Hearing(threading.Thread):
    """Vosk ловит «Сакура». Фразу режет Silero, распознаёт Vosk."""

    def __init__(self, agent):
        super().__init__(daemon=True)
        self.agent         = agent
        self.ok            = bool(sd and np and torch and VoskModel
                                  and load_silero_vad)
        self._follow_until = 0.0
        self._dialog       = False
        self._mute_until   = 0.0
        self.vad           = None
        self.recognizer    = None
        if self.ok:
            try:
                self.vad = SileroVAD()
            except Exception as e:
                log.error(f"Silero VAD не загрузился: {e}")
                self.ok = False
            try:
                self.recognizer = SpeechRecognizer()
            except Exception as e:
                log.error(f"SpeechRecognizer не создался: {e}")
                self.ok = False

    def open_followup(self, seconds: float = config.FOLLOWUP_SEC):
        self._follow_until = time.monotonic() + seconds

    def run(self):
        if not self.ok:
            missing = []
            if not sd:               missing.append("sounddevice")
            if not np:               missing.append("numpy")
            if not torch:            missing.append("torch")
            if not VoskModel:        missing.append("vosk")
            if not load_silero_vad:  missing.append("silero-vad")
            log.warning(f"Слух выключен. Отсутствует: {', '.join(missing) or 'инициализация упала'}")
            log.warning("Установи: pip install vosk silero-vad sounddevice")
            return
            if not VoskModel:        missing.append("vosk")
            if not load_silero_vad:  missing.append("silero-vad")
            log.warning(f"Слух выключен. Отсутствует: {', '.join(missing) or 'инициализация упала'}")
            log.warning("Установи: pip install vosk silero-vad sounddevice")
            return
        if not os.path.isdir(config.VOSK_MODEL_PATH):
            log.warning(f"Слух выключен: нет модели Vosk в {config.VOSK_MODEL_PATH}")
            log.warning("Скачай: https://alphacephei.com/vosk/models → vosk-model-small-ru-0.22")
            return
        try:
            model = VoskModel(config.VOSK_MODEL_PATH)
        except Exception as e:
            log.error(f"Слух: модель Vosk не загрузилась: {e}")
            return

        wake = KaldiRecognizer(model, config.MIC_RATE)
        log.info("Слух включён. Жду «Сакура…»")
        try:
            with sd.RawInputStream(samplerate=config.MIC_RATE, channels=1,
                                   dtype="int16", blocksize=config.MIC_BLOCK) as stream:
                while True:
                    data = bytes(stream.read(config.MIC_BLOCK)[0])

                    if self.agent.player.is_playing():
                        wake = KaldiRecognizer(model, config.MIC_RATE)
                        self._mute_until = time.monotonic() + _TTS_TAIL
                        continue

                    if time.monotonic() < self._mute_until:
                        continue

                    if self._dialog or time.monotonic() < self._follow_until:
                        self._follow_until = 0.0
                        self._capture(stream)
                        continue

                    wake.AcceptWaveform(data)
                    partial = json.loads(wake.PartialResult()).get("partial", "")
                    if any(w in partial for w in config.WAKE_WORDS):
                        wake = KaldiRecognizer(model, config.MIC_RATE)
                        self._capture(stream)
        except Exception as e:
            log.error(f"Слух упал: {e}")

    def _capture(self, stream):
        self.agent.set_state("listening")
        self.vad.reset()
        pcm       = bytearray()
        speaking  = False
        silence   = 0.0
        start     = time.monotonic()
        frame_dur = SileroVAD.FRAME / config.MIC_RATE

        while True:
            if self.agent.player.is_playing():
                self._mute_until = time.monotonic() + _TTS_TAIL
                self.agent.set_state("idle")
                return

            data    = bytes(stream.read(config.MIC_BLOCK)[0])
            elapsed = time.monotonic() - start

            if self.vad.speech_prob(data) >= config.VAD_THRESHOLD:
                speaking, silence = True, 0.0
                pcm.extend(data)
            elif speaking:
                pcm.extend(data)
                silence += frame_dur
                if silence >= config.VAD_END_SILENCE:
                    break
            elif elapsed >= config.VAD_START_TIMEOUT:
                self.agent.set_state("idle")
                return

            if elapsed >= config.MAX_UTTER_SEC:
                break

        if not speaking:
            self.agent.set_state("idle")
            return

        self.agent.set_state("thinking")
        audio = np.frombuffer(bytes(pcm), dtype=np.int16).astype(np.float32) / 32768.0

        try:
            text = self.recognizer.transcribe(audio)
        except Exception as e:
            log.error(f"Распознавание не удалось: {e}")
            self.agent.set_state("idle")
            return

        if not text:
            self.agent.set_state("idle")
            return

        log.info(f"[STT] {text!r}")

        # Анализ просодии — мягко влияет на настроение
        prosody = analyze_voice_emotion(bytes(pcm))
        if prosody["label"] != "neutral":
            apply_voice_emotion(prosody)
            self.agent.last_voice_prosody = prosody

        # Голосовая закладка (Фаза 5)
        tl = text.lower()
        if any(kw in tl for kw in _BOOKMARK_KW):
            content = _BOOKMARK_RE.sub("", text).strip(" ,.—")
            if len(content) > 2:
                self.agent.bus.emit("voice_bookmark", text=content)
                log.info(f"[bookmark] {content[:60]}")
                return

        if self._maybe_game_mode(text):
            return
        self._update_dialog(text)
        self.agent.submit_user_text(text)

    def _maybe_game_mode(self, text: str) -> bool:
        import difflib
        low   = text.lower()
        words = low.replace(",", " ").split()

        def has(targets, cutoff=0.75):
            return any(difflib.get_close_matches(w, targets, n=1, cutoff=cutoff) for w in words)

        # Разговорный контекст — не триггерим команду
        # Если пользователь говорит "про игровой", "по поводу", "надо дополнить" и т.д.
        _conversation_markers = (
            "про ", "по поводу", "про то", "насчёт", "на счет",
            "надо", "нужен", "нужно", "нужна", "дополнить", "изменить",
            "улучшить", "убрать", "добавить", "что думаешь", "как насчёт",
            "стоит ли", "может быть", "может он", "а может",
        )
        if any(m in low for m in _conversation_markers):
            return False

        # Вопрос — не триггерим команду
        if low.endswith("?") and not any(w in low for w in ("включи", "выключи", "открой")):
            return False

        if ((("выйди" in low) or ("выход" in low) or ("обычный" in low) or ("выключи" in low))
                and (has(("игровой", "игры", "игру")) or "режим" in low)):
            self.agent.bus.emit("game_mode", on=False)
            self.agent.set_state("idle")
            log.info("[game] игровой режим ВЫКЛ")
            return True
        if has(("игровой", "игру", "игры")) and "режим" in low:
            self.agent.bus.emit("game_mode", on=True)
            self.agent.set_state("idle")
            log.info("[game] игровой режим ВКЛ")
            return True
        return False

    def _update_dialog(self, text: str):
        import difflib
        words = text.lower().replace(",", " ").split()

        def has(targets, cutoff=0.75):
            return any(difflib.get_close_matches(w, targets, n=1, cutoff=cutoff) for w in words)

        if not self._dialog and has(("поболтаем", "поболтать", "поговорим", "болтать")):
            self._dialog = True
            log.info("[dialog] режим диалога ВКЛ")
        elif self._dialog and len(words) <= 4 and has(
                ("хватит", "всё", "стоп", "спасибо", "пока", "достаточно", "закончили")):
            self._dialog = False
            log.info("[dialog] режим диалога ВЫКЛ")