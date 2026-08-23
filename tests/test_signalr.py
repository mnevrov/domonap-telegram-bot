import asyncio
import json
from collections.abc import Callable

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from domonap_bot.domonap.signalr import (
    SIGNALR_USER_AGENT,
    DomonapSignalRTransport,
    split_signalr_records,
)


def _push_record(
    *,
    event: str = "DomofonCalling",
    call_id: str = "call-1",
    door_id: str | None = "door-1",
) -> str:
    push: dict[str, object] = {
        "EventMessage": event,
        "CallId": call_id,
        "Address": "Test address",
    }
    if door_id is not None:
        push["DoorId"] = door_id
    return json.dumps(
        {
            "type": 1,
            "target": "ReceivePush",
            "arguments": ["unused-0", "unused-1", push],
        }
    )


async def _start_server(app: web.Application) -> TestServer:
    server = TestServer(app)
    await server.start_server()
    return server


def _unsafe_session_factory() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))


def test_split_signalr_records_handles_batched_frames() -> None:
    raw = '{}\x1e{"type":6}\x1e' + _push_record() + "\x1e"
    records = split_signalr_records(raw)

    assert records[0] == "{}"
    assert json.loads(records[1]) == {"type": 6}
    assert json.loads(records[2])["target"] == "ReceivePush"


async def test_websocket_transport_uses_signalr_protocol_and_affinity_cookie() -> None:
    observed: dict[str, str] = {}

    async def negotiate(request: web.Request) -> web.Response:
        observed["negotiate_user_agent"] = request.headers.get("User-Agent", "")
        observed["negotiate_instance_id"] = request.headers.get("instanceId", "")
        observed["negotiate_authorization"] = request.headers.get("Authorization", "")
        response = web.json_response({"connectionToken": "connection-1"})
        response.set_cookie("domonap-api-communication-affinity", "backend-a")
        return response

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        observed["ws_user_agent"] = request.headers.get("User-Agent", "")
        observed["ws_instance_id"] = request.headers.get("instanceId", "")
        observed["ws_authorization"] = request.headers.get("Authorization", "")
        observed["ws_cookie"] = request.headers.get("Cookie", "")

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        observed["handshake"] = await asyncio.wait_for(ws.receive_str(), timeout=1.0)
        observed["keepalive"] = await asyncio.wait_for(ws.receive_str(), timeout=1.0)
        await ws.send_str('{}\x1e{"type":6}\x1e' + _push_record() + "\x1e")
        await asyncio.sleep(0.05)
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_post("/notificationHub/negotiate", negotiate)
    app.router.add_get("/notificationHub", websocket)
    server = await _start_server(app)

    transport = DomonapSignalRTransport(
        base_url=str(server.make_url("/")).rstrip("/"),
        token_provider=lambda: "access-1",
        refresh_callback=AsyncBoolCallback(False),
        keepalive_interval=0.01,
        server_timeout=1.0,
        session_factory=_unsafe_session_factory,
    )
    listener = transport.listen()
    try:
        payload = await asyncio.wait_for(anext(listener), timeout=2.0)
    finally:
        await listener.aclose()
        await transport.close()
        await server.close()

    assert payload.call_id == "call-1"
    assert payload.door_id == "door-1"
    assert payload.address == "Test address"
    assert payload.raw["EventMessage"] == "DomofonCalling"
    assert observed["negotiate_user_agent"] == SIGNALR_USER_AGENT
    assert observed["ws_user_agent"] == SIGNALR_USER_AGENT
    assert observed["negotiate_instance_id"] == ""
    assert observed["ws_instance_id"] == ""
    assert observed["negotiate_authorization"] == "Bearer access-1"
    assert observed["ws_authorization"] == "Bearer access-1"
    assert "domonap-api-communication-affinity=backend-a" in observed["ws_cookie"]
    assert observed["handshake"] == '{"protocol":"json","version":1}\x1e'
    assert observed["keepalive"] == '{"type":6}\x1e'


class AsyncBoolCallback:
    def __init__(self, result: bool, on_call: Callable[[], None] | None = None) -> None:
        self.result = result
        self.on_call = on_call
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        return self.result


async def test_negotiate_401_refreshes_and_retries() -> None:
    token = "old-access"
    negotiate_calls = 0

    async def negotiate(request: web.Request) -> web.Response:
        nonlocal negotiate_calls
        negotiate_calls += 1
        if request.headers.get("Authorization") == "Bearer old-access":
            return web.Response(status=401)
        return web.json_response({"connectionToken": "connection-2"})

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.receive_str()
        await ws.send_str(_push_record(call_id="call-2", door_id="door-2") + "\x1e")
        await asyncio.sleep(0.05)
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_post("/notificationHub/negotiate", negotiate)
    app.router.add_get("/notificationHub", websocket)
    server = await _start_server(app)

    def replace_token() -> None:
        nonlocal token
        token = "new-access"

    refresh = AsyncBoolCallback(True, replace_token)
    transport = DomonapSignalRTransport(
        base_url=str(server.make_url("/")).rstrip("/"),
        token_provider=lambda: token,
        refresh_callback=refresh,
        keepalive_interval=10.0,
        server_timeout=1.0,
        session_factory=_unsafe_session_factory,
    )
    listener = transport.listen()
    try:
        payload = await asyncio.wait_for(anext(listener), timeout=2.0)
    finally:
        await listener.aclose()
        await transport.close()
        await server.close()

    assert payload.call_id == "call-2"
    assert refresh.calls == 1
    assert negotiate_calls == 2


def test_call_ended_clears_active_call_mapping() -> None:
    transport = DomonapSignalRTransport(
        base_url="https://api.domonap.ru",
        token_provider=lambda: "access",
        refresh_callback=AsyncBoolCallback(False),
    )

    incoming = transport._handle_record(_push_record())
    assert incoming is not None
    assert transport._active_calls == {"call-1": "door-1"}

    ended = transport._handle_record(
        _push_record(event="DomofonCallEnded", call_id="call-1", door_id=None)
    )
    assert ended is None
    assert transport._active_calls == {}
