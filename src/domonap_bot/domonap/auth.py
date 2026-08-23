import logging
from typing import Any

import httpx

from domonap_bot.domonap.exceptions import ApiError, AuthenticationError, NetworkError

logger = logging.getLogger(__name__)

_TRUSTED_API_SCHEME = "https"
_TRUSTED_API_HOST = "api.domonap.ru"
_TRUSTED_API_PORT = 443


async def _strip_cross_origin_authorization(request: httpx.Request) -> None:
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    is_trusted_origin = (
        request.url.scheme == _TRUSTED_API_SCHEME
        and request.url.host == _TRUSTED_API_HOST
        and port == _TRUSTED_API_PORT
    )
    if not is_trusted_origin:
        request.headers.pop("Authorization", None)


class DomonapAuth:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        request_hooks = self._http.event_hooks.setdefault("request", [])
        if _strip_cross_origin_authorization not in request_hooks:
            request_hooks.append(_strip_cross_origin_authorization)

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
        logger.warning("SMS request failed (%s): %s", resp.status_code, body)
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
