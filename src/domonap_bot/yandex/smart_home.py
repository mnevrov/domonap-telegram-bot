from __future__ import annotations

import copy
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx
from aiohttp import web

from domonap_bot.yandex.active_call import ActiveCallRegistry

logger = logging.getLogger(__name__)

_DEVICE_ID = "domonap-active-intercom"
_CAPABILITY_ON_OFF = "devices.capabilities.on_off"
_MAX_IDENTITY_CACHE = 128
_MAX_REQUEST_CACHE = 256


class DoorOpener(Protocol):
    async def open_door(self, door_id: str) -> bool: ...


@dataclass(frozen=True)
class YandexIdentity:
    user_id: str
    login: str


@dataclass(frozen=True)
class _CachedIdentity:
    identity: YandexIdentity
    expires_at: float


class YandexIdTokenVerifier:
    """Validate Smart Home bearer tokens against Yandex ID.

    Raw tokens are never persisted or logged. The in-memory cache is keyed by a SHA-256
    digest and additionally pins the OAuth application client ID.
    """

    def __init__(
        self,
        *,
        expected_client_id: str,
        allowed_user_ids: set[str],
        cache_ttl_seconds: float = 300.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        client_id = expected_client_id.strip()
        allowed = {str(item).strip() for item in allowed_user_ids if str(item).strip()}
        if not client_id:
            raise ValueError("expected_client_id must not be empty")
        if not allowed:
            raise ValueError("allowed_user_ids must not be empty")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")

        self._expected_client_id = client_id
        self._allowed_user_ids = allowed
        self._cache_ttl = cache_ttl_seconds
        self._cache: OrderedDict[str, _CachedIdentity] = OrderedDict()
        self._http = http_client or httpx.AsyncClient(
            base_url="https://login.yandex.ru",
            timeout=httpx.Timeout(5.0, connect=3.0),
        )
        self._owns_http = http_client is None

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _cached(self, digest: str) -> YandexIdentity | None:
        cached = self._cache.get(digest)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            self._cache.pop(digest, None)
            return None
        self._cache.move_to_end(digest)
        return cached.identity

    async def verify(self, token: str) -> YandexIdentity | None:
        raw_token = token.strip()
        if not raw_token:
            return None

        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        cached = self._cached(digest)
        if cached is not None:
            return cached

        try:
            response = await self._http.get(
                "/info",
                params={"format": "json"},
                headers={"Authorization": f"OAuth {raw_token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning("Yandex ID token verification transport failed: %s", type(exc).__name__)
            return None

        if not response.is_success:
            logger.warning("Yandex ID token verification failed: HTTP %s", response.status_code)
            return None

        try:
            data: Any = response.json()
        except ValueError:
            logger.warning("Yandex ID token verification returned invalid JSON")
            return None
        if not isinstance(data, dict):
            return None

        user_id = str(data.get("id") or "").strip()
        client_id = str(data.get("client_id") or "").strip()
        login = str(data.get("login") or "").strip()
        if client_id != self._expected_client_id or user_id not in self._allowed_user_ids:
            logger.warning(
                "Yandex Smart Home authorization rejected: user_allowed=%s client_match=%s",
                user_id in self._allowed_user_ids,
                client_id == self._expected_client_id,
            )
            return None

        identity = YandexIdentity(user_id=user_id, login=login)
        self._cache[digest] = _CachedIdentity(
            identity=identity,
            expires_at=time.monotonic() + self._cache_ttl,
        )
        self._cache.move_to_end(digest)
        while len(self._cache) > _MAX_IDENTITY_CACHE:
            self._cache.popitem(last=False)
        return identity


class YandexSmartHomeService:
    def __init__(
        self,
        opener: DoorOpener,
        active_calls: ActiveCallRegistry,
        *,
        dry_run: bool = True,
        max_cached_requests: int = _MAX_REQUEST_CACHE,
    ) -> None:
        if max_cached_requests <= 0:
            raise ValueError("max_cached_requests must be positive")
        self._opener = opener
        self._active_calls = active_calls
        self._dry_run = dry_run
        self._max_cached_requests = max_cached_requests
        self._request_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @staticmethod
    def discovery(request_id: str, user_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "payload": {
                "user_id": user_id,
                "devices": [
                    {
                        "id": _DEVICE_ID,
                        "name": "Домофон",
                        "description": "Активный звонок Domonap",
                        "room": "Прихожая",
                        "type": "devices.types.openable",
                        "custom_data": {"kind": "active_call"},
                        "capabilities": [
                            {
                                "type": _CAPABILITY_ON_OFF,
                                "retrievable": False,
                            }
                        ],
                        "properties": [],
                    }
                ],
            },
        }

    @staticmethod
    def query(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        requested = payload.get("devices")
        devices: list[dict[str, Any]] = []
        if isinstance(requested, list):
            for item in requested:
                if not isinstance(item, dict):
                    continue
                device_id = str(item.get("id") or "")
                if device_id == _DEVICE_ID:
                    # The on/off capability is retrievable=false, so state is omitted.
                    devices.append({"id": _DEVICE_ID, "capabilities": [], "properties": []})
                else:
                    devices.append(
                        {
                            "id": device_id,
                            "error_code": "DEVICE_NOT_FOUND",
                        }
                    )
        return {"request_id": request_id, "payload": {"devices": devices}}

    @staticmethod
    def _device_error(device_id: str, code: str, message: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": device_id,
            "action_result": {"status": "ERROR", "error_code": code},
        }
        if message:
            result["action_result"]["error_message"] = message
        return result

    @staticmethod
    def _is_open_action(device: dict[str, Any]) -> bool:
        capabilities = device.get("capabilities")
        if not isinstance(capabilities, list) or len(capabilities) != 1:
            return False
        capability = capabilities[0]
        if not isinstance(capability, dict) or capability.get("type") != _CAPABILITY_ON_OFF:
            return False
        state = capability.get("state")
        return (
            isinstance(state, dict)
            and state.get("instance") == "on"
            and state.get("value") is True
        )

    def _cached_action(self, request_id: str) -> dict[str, Any] | None:
        cached = self._request_cache.get(request_id)
        if cached is None:
            return None
        self._request_cache.move_to_end(request_id)
        return copy.deepcopy(cached)

    def _cache_action(self, request_id: str, response: dict[str, Any]) -> None:
        self._request_cache[request_id] = copy.deepcopy(response)
        self._request_cache.move_to_end(request_id)
        while len(self._request_cache) > self._max_cached_requests:
            self._request_cache.popitem(last=False)

    async def action(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        cached = self._cached_action(request_id)
        if cached is not None:
            return cached

        requested = payload.get("devices")
        if not isinstance(requested, list) or len(requested) != 1:
            response = {
                "request_id": request_id,
                "payload": {
                    "devices": [
                        self._device_error(
                            _DEVICE_ID,
                            "INVALID_ACTION",
                            "Exactly one Domonap device action is required",
                        )
                    ]
                },
            }
            self._cache_action(request_id, response)
            return response

        raw_device = requested[0]
        if not isinstance(raw_device, dict):
            device = {}
        else:
            device = cast(dict[str, Any], raw_device)
        device_id = str(device.get("id") or "")

        if device_id != _DEVICE_ID:
            result = self._device_error(device_id, "DEVICE_NOT_FOUND")
        elif not self._is_open_action(device):
            result = self._device_error(
                device_id,
                "INVALID_ACTION",
                "Only opening the active intercom call is supported",
            )
        else:
            claimed = await self._active_calls.claim_openable()
            if claimed is None:
                result = self._device_error(
                    device_id,
                    "DEVICE_UNREACHABLE",
                    "There is no single active live Domonap call",
                )
            else:
                success = self._dry_run
                if self._dry_run:
                    logger.info(
                        "Yandex Smart Home dry-run open accepted: call_id=%s door_id=%s",
                        claimed.call_id,
                        claimed.door_id,
                    )
                else:
                    try:
                        success = await self._opener.open_door(claimed.door_id)
                    except Exception as exc:
                        logger.warning(
                            "Yandex Smart Home Domonap open failed: call_id=%s door_id=%s error=%s",
                            claimed.call_id,
                            claimed.door_id,
                            type(exc).__name__,
                        )
                        success = False

                if success:
                    await self._active_calls.complete(claimed.call_id)
                    result = {"id": device_id, "action_result": {"status": "DONE"}}
                else:
                    await self._active_calls.release(claimed.call_id)
                    result = self._device_error(device_id, "DEVICE_UNREACHABLE")

        response = {"request_id": request_id, "payload": {"devices": [result]}}
        self._cache_action(request_id, response)
        return response


class YandexSmartHomeServer:
    def __init__(
        self,
        service: YandexSmartHomeService,
        verifier: YandexIdTokenVerifier,
    ) -> None:
        self._service = service
        self._verifier = verifier

    @staticmethod
    def _request_id(request: web.Request) -> str:
        return request.headers.get("X-Request-Id", "").strip()

    async def _identity(self, request: web.Request) -> YandexIdentity:
        header = request.headers.get("Authorization", "")
        scheme, separator, token = header.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise web.HTTPUnauthorized()
        identity = await self._verifier.verify(token)
        if identity is None:
            raise web.HTTPUnauthorized()
        return identity

    async def _head(self, request: web.Request) -> web.Response:
        del request
        return web.Response(status=200)

    async def _unlink(self, request: web.Request) -> web.Response:
        await self._identity(request)
        request_id = self._request_id(request)
        logger.info("Yandex Smart Home account unlink: request_id=%s", request_id or "<missing>")
        return web.json_response({"request_id": request_id})

    async def _devices(self, request: web.Request) -> web.Response:
        identity = await self._identity(request)
        request_id = self._request_id(request)
        logger.info("Yandex Smart Home discovery: request_id=%s", request_id or "<missing>")
        return web.json_response(self._service.discovery(request_id, identity.user_id))

    @staticmethod
    async def _json_payload(request: web.Request) -> dict[str, Any]:
        try:
            body: Any = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid JSON object")
        payload = body.get("payload", body)
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Invalid payload")
        return cast(dict[str, Any], payload)

    async def _query(self, request: web.Request) -> web.Response:
        await self._identity(request)
        request_id = self._request_id(request)
        payload = await self._json_payload(request)
        logger.info("Yandex Smart Home query: request_id=%s", request_id or "<missing>")
        return web.json_response(self._service.query(request_id, payload))

    async def _action(self, request: web.Request) -> web.Response:
        await self._identity(request)
        request_id = self._request_id(request)
        if not request_id:
            raise web.HTTPBadRequest(text="X-Request-Id is required")
        payload = await self._json_payload(request)
        logger.info(
            "Yandex Smart Home action: request_id=%s dry_run=%s",
            request_id,
            self._service.dry_run,
        )
        return web.json_response(await self._service.action(request_id, payload))

    def app(self) -> web.Application:
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_head("/v1.0", self._head)
        app.router.add_head("/v1.0/", self._head)
        app.router.add_post("/v1.0/user/unlink", self._unlink)
        app.router.add_get("/v1.0/user/devices", self._devices)
        app.router.add_post("/v1.0/user/devices/query", self._query)
        app.router.add_post("/v1.0/user/devices/action", self._action)
        return app

    async def close(self) -> None:
        await self._verifier.close()


async def start_yandex_smart_home(
    server: YandexSmartHomeServer,
    host: str,
    port: int,
) -> web.AppRunner:
    runner = web.AppRunner(server.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


async def stop_yandex_smart_home(
    runner: web.AppRunner,
    server: YandexSmartHomeServer,
) -> None:
    await runner.cleanup()
    await server.close()
