"""desktop.core.chat_turns — ходы чата: всё, что сказала и сделала Сакура, по ходам (turn).

Ход начинается репликой пользователя (микрофон, окно, Telegram, проверка, система) и
собирает все ответы Сакуры по порядку:
  llm        — ответ модели;
  ack        — быстрый ответ без модели («Готово.», «Выполняю.»);
  template   — шаблонная или кэшированная фраза;
  error      — ошибка;
  proactive  — сообщение без запроса (брифинг, напоминание);
  command    — результат команды («Громкость 70%») — из command_result, приглушённой строкой;
  voice_only — звук был, а текста нет: «голосовой ответ (текст недоступен)».

Сервер пока присылает reply {text} без kind и turn_id — такой ответ считается llm и
прикрепляется к текущему ходу; reply вне хода — proactive. Повтор (turn_id, kind, text)
не дублируется. Часы и планировщик передаются снаружи — модуль чистый и тестируемый.
"""
import itertools
import logging
import time
from collections.abc import Callable

log = logging.getLogger("sakura.chat")

# confirm — вопрос сервера «Да или нет?» (выключение, перезагрузка, сон): в окне — кнопки «Да»/«Нет».
KINDS = ("llm", "ack", "template", "error", "proactive", "command", "voice_only", "confirm")
VOICE_ONLY_TEXT = "голосовой ответ (текст недоступен)"
# Сколько ждать текст после tts_end, прежде чем показать заглушку.
TEXT_AFTER_AUDIO_S = 1.5


class ChatTurns:
    def __init__(self, emit: Callable[[dict], None], device: str = "",
                 clock: Callable[[], float] = time.time,
                 schedule: Callable[[float, Callable[[], None]], None] | None = None):
        self._emit = emit
        self._device = device
        self._clock = clock
        self._schedule = schedule or (lambda delay, fn: None)
        self._ids = itertools.count(1)
        self._turn: str | None = None          # текущий ход
        self._audio: set[str] = set()          # ходы, в которых был звук
        self._texted: set[str] = set()         # ходы, где Сакура ответила текстом
        self._checking: set[str] = set()       # ходы, для которых проверка текста уже назначена
        self._seen: set[tuple] = set()         # (turn_id, kind, text) — защита от повторов
        self._msg_ids = itertools.count(1)

    @property
    def current_turn(self) -> str | None:
        return self._turn

    # ── сообщения ──────────────────────────────────────────────────
    def _message(self, role: str, text: str, turn_id: str | None, kind: str | None,
                 source: str, ts: float | None = None) -> dict | None:
        key = (turn_id, kind, text)
        if key in self._seen:
            return None
        self._seen.add(key)
        msg = {"id": f"local-{int(self._clock() * 1000)}-{next(self._msg_ids)}",
               "ts": ts if ts is not None else self._clock(), "role": role, "text": text,
               "channel": "voice" if source == "mic" else "text", "device": self._device,
               "source": source, "turn_id": turn_id}
        if kind:
            msg["kind"] = kind
        self._emit({"type": "chat_message", "message": msg})
        return msg

    def user(self, text: str, source: str = "mic") -> str:
        """Новая реплика пользователя — новый ход."""
        # Прошлый ход со звуком, но без tts_end (озвучку прервали) — тоже проверить на текст.
        self._schedule_checks()
        self._turn = f"t{next(self._ids)}"
        self._message("user", text, self._turn, None, source)
        return self._turn

    def reply(self, text: str, kind: str | None = None, turn_id: str | None = None,
              ts: float | None = None) -> dict | None:
        """Реплика Сакуры. Без turn_id — к текущему ходу; без хода — проактивная."""
        text = (text or "").strip()
        if not text:
            return None
        turn = turn_id or self._turn
        kind = kind if kind in KINDS else ("llm" if turn else "proactive")
        if turn is None and kind != "confirm":
            kind = "proactive"
        msg = self._message("assistant", text, turn, kind, "server", ts)
        if msg is not None and turn:
            self._texted.add(turn)
        return msg

    def command(self, detail: str, status: str, action: str = "") -> dict | None:
        """Результат команды — приглушённой строкой «действие» в текущем ходе."""
        detail = (detail or "").strip()
        if not detail:
            return None
        kind = "command" if status == "done" else "error"
        text = detail if status == "done" else f"Не получилось: {detail}"
        return self._message("system", text, self._turn, kind, "system")

    # ── звук без текста ────────────────────────────────────────────
    def audio(self):
        """Для текущего хода пришёл звук (tts_chunk)."""
        if self._turn:
            self._audio.add(self._turn)

    def tts_end(self):
        """Озвучка кончилась: если текста так и не будет — заглушка и WARNING."""
        self._schedule_checks()

    def _schedule_checks(self):
        # Все ходы со звуком без текста, а не только текущий: при быстрых ходах новый ход
        # начинается раньше, чем кончилась озвучка прошлого, — его заглушка не должна пропасть.
        for turn in sorted(self._audio - self._texted - self._checking):
            self._checking.add(turn)
            self._schedule(TEXT_AFTER_AUDIO_S, lambda t=turn: self._check_text(t))

    def _check_text(self, turn: str):
        if turn in self._texted:
            return
        log.warning("[chat] звук без текста: turn_id=%s kind=llm — сервер не прислал reply", turn)
        self._message("assistant", VOICE_ONLY_TEXT, turn, "voice_only", "server")
        self._texted.add(turn)
