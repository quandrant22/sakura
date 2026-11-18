"""Фразы встроенной Яндекс.Музыки: реестр выбирает нужное действие и передаёт запрос."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from sakura_core.bridge import _load_capabilities
from sakura_core.bridge import confirms_via_executor
from sakura_core.executor import AgentCommand, ExecutionContext, Executor, get_handler
from sakura_core.registry import build_index, load
from sakura_core.session import Session

_load_capabilities()
DECLS = load()
INDEX = build_index(DECLS)


@pytest.mark.parametrize("text,action,param", [
    ("включи альбом Nevermind", "music.play_album", "Nevermind"),
    ("включи плейлист Бег", "music.play_playlist", "Бег"),
    ("Запусти плейлист джепэнвел мэ", "music.play_playlist", "джепэнвел мэ"),
    ("запусти альбом Nevermind", "music.play_album", "Nevermind"),
    ("запусти трек Nirvana", "music.play_track", "Nirvana"),
    ("включи трек Nirvana", "music.play_track", "Nirvana"),
    ("поставь песню Группа крови", "music.play_track", "Группа крови"),
    ("запусти мою волну", "music.wave", None),
    ("запусти плейлист дня", "music.playlist_of_day", None),
    ("включи плейлист дня", "music.playlist_of_day", None),
    ("включи исполнителя Земфира", "music.play_artist", "Земфира"),
    ("добавь в очередь Smells Like Teen Spirit", "music.queue_add", "Smells Like Teen Spirit"),
    ("добавь Nirvana в очередь", "music.queue_add", "Nirvana"),
    ("поставь Nirvana следующим", "music.play_next", "Nirvana"),
    ("что в очереди", "music.queue_show", None),
    ("очисти очередь", "music.queue_clear", None),
    ("убери из очереди Nirvana", "music.queue_remove", "Nirvana"),
    ("найди музыку для бега", "music.search", "для бега"),
    ("включи радио рок", "music.station", "рок"),
    ("включи похожее", "music.similar", None),
    ("убери лайк", "music.unlike", None),
    ("добавь в плейлист Бег", "music.playlist_add", "в плейлист Бег"),
    ("добавь Nirvana в плейлист Бег", "music.playlist_add", "Nirvana в плейлист Бег"),
    ("убери из плейлиста Бег", "music.playlist_remove", "Бег"),
    ("создай плейлист Дорога", "music.playlist_create", "Дорога"),
    ("удали плейлист Дорога", "music.playlist_delete", "Дорога"),
    ("громкость музыки 40", "music.volume_set", "40"),
])
def test_phrase_to_action(text, action, param):
    hit = INDEX.match(text)
    assert hit is not None and hit[1].id == action and hit[2] == param


def test_seek_to_only_while_music_plays():
    assert INDEX.match("перемотай на 1:30", "playing:music")[1].id == "music.seek_to"
    assert INDEX.match("перемотай на 1:30") is None


@pytest.mark.parametrize("text", ["кто будет следующим", "стоял в очередь", "дописал в плейлист"])
def test_common_speech_is_not_a_command(text):
    assert INDEX.match(text) is None


def test_playlist_delete_requires_confirmation():
    decl = {d.id: d for d in DECLS}["music.playlist_delete"]
    assert decl.confirm is True and decl.reversible is False


def test_playlist_delete_asks_first_and_keeps_the_name_until_yes():
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(json.loads(raw))

    session = Session()
    ex = Executor(session=session)
    ctx = ExecutionContext(device_ws=WS(), device_id="pc", register_command=lambda a, d: "c1", extra={"text": "удали"})
    reply = asyncio.run(ex.execute("music.playlist_delete", ctx, param="Дорога"))
    assert reply == ("Удалить плейлист целиком?", True) and sent == []        # без «да» ничего не ушло
    assert confirms_via_executor("music.playlist_delete")
    prepared = session.pending.payload["command"]
    assert prepared == {"action": "music.playlist_delete", "arg": "Дорога"}
    yes = ExecutionContext(device_ws=WS(), device_id="pc", register_command=lambda a, d: "c2",
                           extra={"text": "да", "confirmed": True, "prepared_command": prepared})
    asyncio.run(ex.execute("music.playlist_delete", yes, param="Дорога"))
    assert sent[0]["action"] == "music.playlist_delete" and sent[0]["arg"] == "Дорога" and sent[0]["confirmed"] is True


@pytest.mark.parametrize("action,param,want", [
    ("music.play_track", "Nirvana в очередь", AgentCommand("music.queue_add", "Nirvana")),
    ("music.play_track", "Nirvana следующим", AgentCommand("music.play_next", "Nirvana")),
    ("music.play_album", "Nevermind в очередь", AgentCommand("music.queue_add", "альбом Nevermind")),
    ("music.play_playlist", "Бег следующим", AgentCommand("music.play_next", "плейлист Бег")),
    ("music.play_track", "Nirvana", AgentCommand("music.play_track", "Nirvana")),
])
def test_queue_tail_wins_over_play_verb(action, param, want):
    assert get_handler(action)(ExecutionContext(param=param)) == want


def test_query_comes_from_extra_too():
    ctx = SimpleNamespace(param=None, extra={"query": " Бег "})
    assert get_handler("music.playlist_create")(ctx) == AgentCommand("music.playlist_create", "Бег")
