import logging
from typing import Any, cast

import httpx

from domonap_bot.domonap.auth import DomonapAuth
from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    TokenExpiredError,
)
from domonap_bot.domonap.models import AuthSession, CallLogEntry, Door
from domonap_bot.storage.tokens import TokenStorage

logger = logging.getLogger(__name__)

BASE_URL = "https://api.domonap.ru"


class DomonapClient:
    def __init__(
        self,
        token_storage: TokenStorage,
        phone: str = "",
    ) -> None:
        self._token_storage = token_storage
        self._phone = phone
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(15.0),
        )
        self.auth = DomonapAuth(self._client)

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        token = await self._token_storage.load()
        headers = kwargs.pop("headers", {})
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")

        try:
            resp = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise NetworkError("Request timed out") from exc
        except httpx.ConnectError as exc:
            raise NetworkError("Connection failed") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"HTTP error: {exc}") from exc

        if resp.status_code == 401:
            refreshed = await self._try_refresh()
            if refreshed:
                return await self._request(method, path, **kwargs)
            raise TokenExpiredError("Token expired and could not be refreshed")

        if not resp.is_success:
            raise ApiError(
                f"API returned {resp.status_code}: {resp.text}"
            )

        try:
            return cast("dict[str, Any]", resp.json())
        except Exception as exc:
            raise ApiError("Invalid JSON response") from exc

    async def _try_refresh(self) -> bool:
        refresh_token = await self._token_storage.load_refresh()
        if not refresh_token:
            return False
        try:
            resp = await self._client.post(
                "/api/v2/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            if resp.is_success:
                data = resp.json()
                session = AuthSession(
                    token=data["token"],
                    refresh_token=data.get("refresh_token"),
                    phone=self._phone,
                )
                await self._token_storage.save(session)
                return True
        except Exception:
            logger.warning("Token refresh failed", exc_info=True)
        return False

    @property
    def token_storage(self) -> TokenStorage:
        return self._token_storage

    @property
    def phone(self) -> str:
        return self._phone

    async def login(self, phone: str) -> bool:
        try:
            await self.auth.request_code(phone)
            return True
        except DomonapError:
            return False

    async def confirm_login(self, code: str) -> bool:
        try:
            token = await self.auth.confirm_code(code)
            session = AuthSession(
                token=token,
                phone=self._phone,
            )
            await self._token_storage.save(session)
            return True
        except DomonapError:
            return False

    async def refresh_token(self) -> bool:
        return await self._try_refresh()

    async def get_doors(self) -> list[Door]:
        data = await self._request("GET", "/api/v2/doors")
        return [Door(**item) for item in data.get("doors", [])]

    async def open_door(self, door_id: str) -> bool:
        data = await self._request(
            "POST",
            f"/api/v2/doors/{door_id}/open",
        )
        return bool(data.get("success", False))

    async def get_call_logs(self) -> list[CallLogEntry]:
        data = await self._request("GET", "/api/v2/calls")
        return [CallLogEntry(**item) for item in data.get("calls", [])]

    async def get_video_url(self, door_id: str) -> str | None:
        data = await self._request(
            "GET",
            f"/api/v2/doors/{door_id}/video",
        )
        return data.get("url")

    async def close(self) -> None:
        await self._client.aclose()
