import logging

import httpx
import pytest
import respx
from httpx import Response

from domonap_bot.domonap.auth import DomonapAuth
from domonap_bot.domonap.exceptions import ApiError, AuthenticationError
from domonap_bot.telegram.errors import describe_error

_SENTINEL = "upstream-secret-marker"


def test_api_error_discards_upstream_body() -> None:
    exc = ApiError(f'HTTP 503: {{"detail":"{_SENTINEL}"}}')

    assert str(exc) == "Domonap API request failed (HTTP 503)"
    assert _SENTINEL not in str(exc)
    assert _SENTINEL not in repr(exc)
    assert _SENTINEL not in describe_error(exc)


def test_authentication_error_discards_upstream_body() -> None:
    exc = AuthenticationError(f'HTTP 401: {{"detail":"{_SENTINEL}"}}')

    assert str(exc) == "Domonap authentication failed (HTTP 401)"
    assert _SENTINEL not in str(exc)
    assert _SENTINEL not in repr(exc)


@pytest.mark.asyncio
@respx.mock
async def test_sms_request_failure_does_not_log_response_body(caplog: pytest.LogCaptureFixture) -> None:
    async with httpx.AsyncClient(base_url="https://api.domonap.ru") as http:
        auth = DomonapAuth(http)
        respx.post("https://api.domonap.ru/sso-api/Authorization/Authorize").mock(
            return_value=Response(400, text=_SENTINEL)
        )

        with caplog.at_level(logging.WARNING), pytest.raises(ApiError):
            await auth.request_code("7", "9991234567")

    assert _SENTINEL not in caplog.text
    assert "HTTP 400" in caplog.text
