from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable

import aiohttp
from pydantic import ValidationError

from domonap_bot.domonap.models import IncomingCallPayload

logger = logging.getLogger(__name__)

SIGNALR_USER_AGENT = (
    "Microsoft SignalR/8.0 (8.0.6; Linux; Java; 0; The Android Project)"
)
_SIGNALR_RECORD_SEPARATOR = "\x1e"
_SIGNALR_HANDSHAKE = '{"protocol":"json","version":1}' + _SIGNALR_RECORD_SEPARATOR
_SIGNALR_PING = '{"type":6}' + _SIGNALR_RECORD_SEPARATOR
_DEFAULT_KEEPALIVE_INTERVAL = 15.0
_DEFAULT_SERVER_TIMEOUT = 30.0
_DEFAULT_MAX_RECONNECT_DELAY = 10.0
_MAX_WEBSOCKET_MESSAGE_SIZE = 256 * 1024
_MAX_ACTIVE_CALLS = 1024

TokenProvider = Callable[[], str | None]
RefreshCallback = Callable[[], Awaitable[bool]]
SessionFactory = Callable[[], aiohttp.ClientSession]


class SignalRConnectionError(RuntimeError):
    """The Domonap SignalR connection could not be established or maintained."""


class SignalRAuthenticationError(SignalRConnectionError):
    """The SignalR connection has no usable access token."""


def split_signalr_records(raw: str) -> list[str]:
    """Split one WebSocket frame into SignalR JSON protocol records."""
    return [record for record in raw.split(_SIGNALR_RECORD_SEPARATOR) if record]


class DomonapSignalRTransport:
    """Minimal SignalR JSON-protocol client for Domonap notificationHub."""

    def __init__(
        self,
        *,
        base_url: str,
        token_provider: TokenProvider,
        refresh_callback: RefreshCallback,
        dom_app: str = "mobile;",
        dom_platform: str = "Android;",
        keepalive_interval: float = _DEFAULT_KEEPALIVE_INTERVAL,
        server_timeout: float = _DEFAULT_SERVER_TIMEOUT,
        max_reconnect_delay: float = _DEFAULT_MAX_RECONNECT_DELAY,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_provider = token_provider
        self._refresh_callback = refresh_callback
        self._dom_app = dom_app
        self._dom_platform = dom_platform
        self._keepalive_interval = keepalive_interval
        self._server_timeout = server_timeout
        self._max_reconnect_delay = max_reconnect_delay
        self._session_factory = session_factory

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stop_event = asyncio.Event()
        self._reconnect_delay = 1.0
        self._active_calls: dict[str, str] = {}

    async def close(self) -> None:
        self._stop_event.set()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None

    async def listen_once(self) -> AsyncIterator[IncomingCallPayload]:
        """Run one hub session, retrying only an authentication handshake once."""
        self._stop_event.clear()
        for attempt in range(2):
            try:
                async for payload in self._connect_once():
                    yield payload
                return
            except aiohttp.WSServerHandshakeError as exc:
                if exc.status == 401 and attempt == 0 and await self._refresh_callback():
                    continue
                raise

    async def listen(self) -> AsyncIterator[IncomingCallPayload]:
        """Yield incoming-call pushes, reconnecting when the hub connection drops."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                async for payload in self.listen_once():
                    yield payload
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as exc:
                logger.warning("SignalR WebSocket handshake failed: HTTP %s", exc.status)
            except (aiohttp.ClientError, asyncio.TimeoutError, SignalRConnectionError) as exc:
                logger.warning("SignalR connection failed: %s", exc)

            if self._stop_event.is_set():
                break
            delay = min(self._reconnect_delay, self._max_reconnect_delay)
            await asyncio.sleep(delay + random.uniform(0.0, 0.5))
            self._reconnect_delay = min(delay * 2.0, self._max_reconnect_delay)

    async def _connect_once(self) -> AsyncIterator[IncomingCallPayload]:
        session = await self._ensure_session()
        connection_token = await self._negotiate(session)
        ws_url = self._websocket_url(connection_token)
        access_token = self._token_provider()
        if not access_token:
            raise SignalRAuthenticationError("No access token for WebSocket upgrade")

        headers = self._signalr_headers(access_token)
        keepalive_task: asyncio.Task[None] | None = None
        ws_timeout = aiohttp.ClientWSTimeout(ws_receive=self._server_timeout)
        try:
            async with session.ws_connect(
                ws_url,
                headers=headers,
                timeout=ws_timeout,
                max_msg_size=_MAX_WEBSOCKET_MESSAGE_SIZE,
            ) as ws:
                self._ws = ws
                self._reconnect_delay = 1.0
                logger.info("SignalR WebSocket connected")
                await ws.send_str(_SIGNALR_HANDSHAKE)
                keepalive_task = asyncio.create_task(self._keepalive(ws))

                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        for record in split_signalr_records(message.data):
                            payload = self._handle_record(record)
                            if payload is not None:
                                yield payload
                    elif message.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        error = ws.exception()
                        raise SignalRConnectionError(str(error or "WebSocket error"))
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass
            self._ws = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            if self._session_factory is not None:
                self._session = self._session_factory()
            else:
                timeout = aiohttp.ClientTimeout(total=30.0)
                self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _negotiate(self, session: aiohttp.ClientSession) -> str:
        for attempt in range(2):
            access_token = self._token_provider()
            if not access_token:
                if attempt == 0 and await self._refresh_callback():
                    continue
                raise SignalRAuthenticationError("No access token for SignalR negotiate")

            url = f"{self._base_url}/notificationHub/negotiate?negotiateVersion=1"
            async with session.post(url, headers=self._signalr_headers(access_token)) as response:
                if response.status == 401 and attempt == 0:
                    if await self._refresh_callback():
                        continue
                if not 200 <= response.status < 300:
                    raise SignalRConnectionError(
                        f"SignalR negotiate failed with HTTP {response.status}"
                    )
                try:
                    data = await response.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError) as exc:
                    raise SignalRConnectionError("Invalid SignalR negotiate JSON") from exc
                if not isinstance(data, dict):
                    raise SignalRConnectionError("Unexpected SignalR negotiate response")
                connection_token = data.get("connectionToken")
                if not isinstance(connection_token, str) or not connection_token:
                    raise SignalRConnectionError("Missing connectionToken in negotiate response")
                logger.info("SignalR negotiate succeeded")
                return connection_token

        raise SignalRAuthenticationError("SignalR authentication failed")

    def _signalr_headers(self, access_token: str) -> dict[str, str]:
        return {
            "User-Agent": SIGNALR_USER_AGENT,
            "dom-app": self._dom_app,
            "dom-platform": self._dom_platform,
            "Authorization": f"Bearer {access_token}",
        }

    def _websocket_url(self, connection_token: str) -> str:
        if self._base_url.startswith("https://"):
            base = "wss://" + self._base_url.removeprefix("https://")
        elif self._base_url.startswith("http://"):
            base = "ws://" + self._base_url.removeprefix("http://")
        else:
            raise SignalRConnectionError(f"Unsupported base URL: {self._base_url}")
        return f"{base}/notificationHub?id={connection_token}"

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            while not self._stop_event.is_set() and not ws.closed:
                await asyncio.sleep(self._keepalive_interval)
                if self._stop_event.is_set() or ws.closed:
                    break
                await ws.send_str(_SIGNALR_PING)
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, ConnectionError):
            return

    def _remember_active_call(self, call_id: str, door_id: str) -> None:
        if call_id not in self._active_calls and len(self._active_calls) >= _MAX_ACTIVE_CALLS:
            oldest_call_id = next(iter(self._active_calls))
            self._active_calls.pop(oldest_call_id, None)
        self._active_calls[call_id] = door_id

    def _handle_record(self, record: str) -> IncomingCallPayload | None:
        if record == "{}":
            return None
        try:
            data = json.loads(record)
        except json.JSONDecodeError:
            logger.debug("Ignoring malformed SignalR JSON record")
            return None
        if not isinstance(data, dict):
            return None
        if data.get("type") != 1 or data.get("target") != "ReceivePush":
            return None

        raw_args = data.get("arguments")
        if not isinstance(raw_args, list) or len(raw_args) < 3:
            logger.warning("SignalR ReceivePush has malformed arguments")
            return None
        push_data = raw_args[2]
        if not isinstance(push_data, dict):
            logger.warning("SignalR ReceivePush has malformed payload")
            return None

        event_message = push_data.get("EventMessage")
        call_id = str(push_data.get("CallId") or "")
        door_id = push_data.get("DoorId")
        logger.info(
            "SignalR ReceivePush event=%s call_id=%s door_id=%s",
            event_message or "<missing>",
            call_id or "<missing>",
            door_id or "<missing>",
        )
        if event_message == "DomofonCallEnded":
            if call_id:
                if door_id is None:
                    door_id = self._active_calls.get(call_id)
                self._active_calls.pop(call_id, None)
            logger.debug("Domonap call ended")
            return None

        if event_message != "DomofonCalling":
            return None

        try:
            payload = IncomingCallPayload.model_validate(push_data)
        except ValidationError:
            logger.warning("Invalid Domonap incoming-call push schema")
            return None
        payload.raw = dict(push_data)
        if payload.call_id and payload.door_id:
            self._remember_active_call(payload.call_id, payload.door_id)
        return payload
