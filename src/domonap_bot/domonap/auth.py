import logging
from typing import Any

import httpx

from domonap_bot.domonap.exceptions import ApiError, AuthenticationError, NetworkError

logger = logging.getLogger(__name__)


class DomonapAuth:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def request_code(self, country_code: str, phone_number: str) -> bool:
        payload = {
            "phoneNumber": {
                "countryCode": int(country_code),
                "number": int(phone_number),
            },
        }
        try:
            resp = await self._http.post(
                "/sso-api/Authorization/Authorize",
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise NetworkError("Request timed out") from exc
        except httpx.ConnectError as exc:
            raise NetworkError("Connection failed") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"HTTP error: {exc}") from exc

        if resp.is_success:
            return True

        body = resp.text[:500]
        raise ApiError(f"SMS request failed ({resp.status_code}): {body}")

    async def confirm_code(
        self,
        country_code: str,
        phone_number: str,
        confirm_code: str,
        device_token: str,
    ) -> dict[str, Any]:
        payload = {
            "phoneNumber": {
                "countryCode": int(country_code),
                "number": int(phone_number),
            },
            "confirmCode": confirm_code,
            "deviceToken": device_token,
        }
        try:
            resp = await self._http.post(
                "/sso-api/Authorization/ConfirmAuthorization",
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise NetworkError("Request timed out") from exc
        except httpx.ConnectError as exc:
            raise NetworkError("Connection failed") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"HTTP error: {exc}") from exc

        if not resp.is_success:
            body = resp.text[:500]
            raise AuthenticationError(f"Code confirmation failed ({resp.status_code}): {body}")

        data: dict[str, Any] = resp.json()
        return data
