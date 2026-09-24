import asyncio
import inspect
from types import SimpleNamespace


def _run(coro):
    return asyncio.run(coro)


def _message():
    return SimpleNamespace(from_user=SimpleNamespace(id=123456789))


def test_media_wrappers_accept_full_shared_kwargs(monkeypatch):
    import adapters.telegram as telegram
    from adapters.media import (
        handle_photo_impl,
        handle_video_impl,
        handle_video_note_impl,
        handle_voice_impl,
    )

    monkeypatch.setattr(telegram, "is_master", lambda _user_id: False)
    implementations = (
        handle_voice_impl,
        handle_photo_impl,
        handle_video_impl,
        handle_video_note_impl,
    )

    for implementation in implementations:
        _run(telegram._media_handler(implementation)(_message()))


def test_master_only_wrappers_match_all_registered_commands(monkeypatch):
    import adapters.telegram as telegram
    from adapters.commands import (
        cmd_block_impl,
        cmd_clean_slate_impl,
        cmd_clear_impl,
        cmd_guests_impl,
        cmd_health_impl,
        cmd_help_impl,
        cmd_memory_impl,
        cmd_restart_impl,
        cmd_start_impl,
        cmd_status_impl,
        cmd_tasks_impl,
        cmd_trusted_impl,
        cmd_unvip_impl,
        cmd_users_impl,
        cmd_vip_impl,
    )

    monkeypatch.setattr(telegram, "is_master", lambda _user_id: True)
    commands = (
        (cmd_help_impl, {}),
        (cmd_health_impl, {}),
        (cmd_restart_impl, {}),
        (cmd_start_impl, {"ask_gemini": telegram.ask_gemini}),
        (cmd_status_impl, {}),
        (cmd_memory_impl, {}),
        (cmd_tasks_impl, {}),
        (cmd_clear_impl, {"ask_gemini": telegram.ask_gemini}),
        (cmd_clean_slate_impl, {"clean_slate_fn": telegram.clean_slate}),
        (cmd_guests_impl, {}),
        (cmd_vip_impl, {}),
        (cmd_trusted_impl, {}),
        (cmd_users_impl, {}),
        (cmd_unvip_impl, {}),
        (cmd_block_impl, {}),
    )

    for implementation, extra_kw in commands:
        async def checked(message, _implementation=implementation, **kwargs):
            inspect.signature(_implementation).bind(message, **kwargs)

        _run(telegram._master_only(checked, **extra_kw)(_message()))