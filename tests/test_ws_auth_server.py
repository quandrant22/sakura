"""Integration tests for authentication and frame limits on the VPS WS server."""

import asyncio
import json

import websockets

from adapters.ws import ws_handler
from modules.ws_auth import MAX_WS_MESSAGE_SIZE, _WS_SECRET


async def _with_server(scenario):
    async with websockets.serve(
        ws_handler,
        "127.0.0.1",
        0,
        max_size=MAX_WS_MESSAGE_SIZE,
        ping_interval=None,
    ) as server:
        port = server.sockets[0].getsockname()[1]
        await scenario(f"ws://127.0.0.1:{port}")


def test_connection_without_first_message_is_closed_after_timeout():
    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as client:
            await asyncio.wait_for(client.wait_closed(), timeout=6)
            assert client.close_code == 4401

    asyncio.run(_with_server(scenario))


def test_first_message_with_invalid_token_is_rejected():
    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as client:
            await client.send(json.dumps({"type": "register", "token": "invalid"}))
            await asyncio.wait_for(client.wait_closed(), timeout=2)
            assert client.close_code == 4401

    asyncio.run(_with_server(scenario))


def test_invalid_token_is_rejected_on_every_message():
    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as client:
            await client.send(json.dumps({"type": "unknown", "token": _WS_SECRET}))
            await client.send(json.dumps({"type": "unknown", "token": "invalid"}))
            await asyncio.wait_for(client.wait_closed(), timeout=2)
            assert client.close_code == 4401

    asyncio.run(_with_server(scenario))


def test_frame_larger_than_configured_limit_is_rejected():
    async def scenario(uri):
        async with websockets.connect(uri, max_size=None) as client:
            await client.send("x" * (MAX_WS_MESSAGE_SIZE + 1))
            await asyncio.wait_for(client.wait_closed(), timeout=3)
            assert client.close_code == 1009

    asyncio.run(_with_server(scenario))