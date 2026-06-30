import logging
from typing import Any

import httpx

from domonap_bot.domonap.exceptions import AuthenticationError, NetworkError
from domonap_bot.domonap.models import LoginCodeResponse

logger = logging.getLogger(__name__)


class DomonapAuth:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._session_id: str | None = None

    async def request_code(self, phone: str) -> LoginCodeResponse:
        try:
            resp = await self._http.post(
                "/api/v2/auth/request-code",
                json={"phone": phone},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            self._session_id = str(data["session_id"])
            return LoginCodeResponse(
                session_id=str(data["session_id"]),
                retry_after=int(data.get("retry_after", 30)),
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            raise NetworkError("Failed to request auth code") from exc

    async def confirm_code(self, code: str) -> str:
        if not self._session_id:
            raise AuthenticationError("No active session. Request code first.")
        try:
            resp = await self._http.post(
                "/api/v2/auth/confirm-code",
                json={"session_id": self._session_id, "code": code},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return str(data["token"])
        except AuthenticationError:
            raise
        except Exception as exc:
            raise NetworkError("Failed to confirm auth code") from exc
