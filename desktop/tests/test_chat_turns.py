"""Чат показывает все ответы Сакуры по ходам (п. 1.4): фейковый сервер — вызовы ChatTurns."""
from desktop.core.chat_turns import VOICE_ONLY_TEXT, ChatTurns


class Harness:
    def __init__(self):
        self.out = []
        self.timers = []
        self.t = 1000.0
        self.chat = ChatTurns(self.out.append, device="pc", clock=lambda: self.t,
                              schedule=lambda d, fn: self.timers.append((d, fn)))

    def fire(self):
        timers, self.timers = self.timers, []
        for _, fn in timers:
            fn()

    def msgs(self):
        return [(m["message"]["role"], m["message"].get("kind"), m["message"]["text"], m["message"]["turn_id"])
                for m in self.out]


def test_voice_transcript_and_llm_reply():
    h = Harness()
    t = h.chat.user("Сакура, как дела?", source="mic")
    h.chat.reply("Отлично!")
    assert h.msgs() == [("user", None, "Сакура, как дела?", t), ("assistant", "llm", "Отлично!", t)]
    assert h.out[0]["message"]["source"] == "mic" and h.out[0]["message"]["channel"] == "voice"


def test_command_ack_and_action_line():
    h = Harness()
    t = h.chat.user("сделай потише на двадцать")
    h.chat.reply("Сделано.", kind="ack")
    h.chat.command("громкость 50%", "done")
    assert h.msgs()[1:] == [("assistant", "ack", "Сделано.", t), ("system", "command", "громкость 50%", t)]


def test_error_reply_and_failed_command():
    h = Harness()
    t = h.chat.user("включи волну")
    h.chat.reply("Не вышло.", kind="error")
    h.chat.command("Нет активного плеера", "noop")
    assert h.msgs()[1:] == [("assistant", "error", "Не вышло.", t),
                            ("system", "error", "Не получилось: Нет активного плеера", t)]


def test_proactive_without_turn():
    h = Harness()
    h.chat.reply("Через 10 минут созвон")
    assert h.msgs() == [("assistant", "proactive", "Через 10 минут созвон", None)]
    h.chat.reply("Брифинг готов", kind="proactive", turn_id="srv-7")
    assert h.msgs()[-1] == ("assistant", "proactive", "Брифинг готов", "srv-7")


def test_audio_without_text_gets_placeholder_and_warning(caplog):
    h = Harness()
    t = h.chat.user("как дела?")
    h.chat.audio()
    h.chat.tts_end()
    assert h.timers and h.timers[0][0] == 1.5
    h.fire()
    assert h.msgs()[-1] == ("assistant", "voice_only", VOICE_ONLY_TEXT, t)
    assert any("звук без текста" in r.message and t in r.message for r in caplog.records)


def test_audio_with_late_text_no_placeholder():
    h = Harness()
    h.chat.user("как дела?")
    h.chat.audio()
    h.chat.tts_end()
    h.chat.reply("Хорошо")         # пришёл в течение 1.5 с после tts_end
    h.fire()
    assert [m[1] for m in h.msgs()] == [None, "llm"]


def test_duplicate_reply_ignored():
    h = Harness()
    h.chat.user("привет")
    h.chat.reply("Привет!", kind="llm")
    h.chat.reply("Привет!", kind="llm")
    h.chat.reply("Привет!", kind="ack")   # другой kind — другое сообщение
    assert [m[1] for m in h.msgs()] == [None, "llm", "ack"]


def test_two_fast_turns_keep_order_and_explicit_turn_id():
    h = Harness()
    t1 = h.chat.user("первый")
    t2 = h.chat.user("второй")
    h.chat.reply("ответ на первый", turn_id=t1)   # сервер поздно ответил на первый ход
    h.chat.reply("ответ на второй")
    assert h.msgs() == [("user", None, "первый", t1), ("user", None, "второй", t2),
                        ("assistant", "llm", "ответ на первый", t1), ("assistant", "llm", "ответ на второй", t2)]


def test_fast_turns_placeholder_for_previous_turn_not_lost():
    """Новый ход начался раньше tts_end прошлого — заглушка прошлого хода всё равно появляется."""
    h = Harness()
    t1 = h.chat.user("включи свет", source="mic")
    h.chat.audio()                      # звук ответа на t1, текста нет
    t2 = h.chat.user("и музыку", source="mic")
    h.chat.audio()
    h.chat.tts_end()
    h.fire()
    placeholders = [m for m in h.msgs() if m[1] == "voice_only"]
    assert placeholders == [("assistant", "voice_only", VOICE_ONLY_TEXT, t1),
                            ("assistant", "voice_only", VOICE_ONLY_TEXT, t2)]


def test_interrupted_speech_without_tts_end_still_checked():
    h = Harness()
    t1 = h.chat.user("расскажи сказку", source="mic")
    h.chat.audio()                      # озвучку перебили — tts_end не пришёл
    h.chat.user("стоп", source="mic")
    h.fire()
    assert ("assistant", "voice_only", VOICE_ONLY_TEXT, t1) in h.msgs()


def test_each_voice_turn_gets_text_or_placeholder_once():
    h = Harness()
    turns = []
    for i in range(5):
        turns.append(h.chat.user(f"фраза {i}", source="mic"))
        h.chat.audio()
        if i % 2 == 0:
            h.chat.reply(f"ответ {i}")
        h.chat.tts_end()
    h.fire()
    h.chat.tts_end()
    h.fire()
    for i, t in enumerate(turns):
        answers = [m for m in h.msgs() if m[0] == "assistant" and m[3] == t]
        assert len(answers) == 1, (i, answers)
        assert answers[0][1] == ("llm" if i % 2 == 0 else "voice_only")
