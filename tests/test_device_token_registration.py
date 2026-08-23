import json

import respx
from httpx import Response

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.tokens import TokenStorage
from tests.test_client import FakeStorage

DEVICE_TOKEN = "00000000-0000-4000-8000-000000000001"
INSTANCE_ID = "00000000-0000-4000-8000-000000000002"


def _make_client(*, register_device_token: bool) -> DomonapClient:
    return DomonapClient(
        token_storage=TokenStorage(FakeStorage()),
        phone="+79991234567",
        device_token=DEVICE_TOKEN,
        instance_id=INSTANCE_ID,
        register_device_token=register_device_token,
    )


def _confirmation_response() -> Response:
    return Response(
        200,
        json={
            "completeToken": {
                "accessToken": "access-1",
                "refreshToken": "refresh-1",
                "refreshExpirationDate": "2027-01-01T00:00:00+03:00",
            }
        },
    )


def test_settings_do_not_register_device_token_by_default() -> None:
    settings = Settings(telegram_bot_token="test:token")
    assert settings.domonap_register_device_token is False


@respx.mock
async def test_confirm_keeps_device_token_in_auth_but_skips_registration_by_default() -> None:
    client = _make_client(register_device_token=False)
    confirm_route = respx.post(
        "https://api.domonap.ru/sso-api/Authorization/ConfirmAuthorization"
    ).mock(return_value=_confirmation_response())
    update_route = respx.post(
        "https://api.domonap.ru/sso-api/Authorization/UpdateDeviceToken"
    ).mock(return_value=Response(200, text="ok"))

    try:
        success = await client.confirm_login("1234")
    finally:
        await client.close()

    assert success is True
    assert confirm_route.call_count == 1
    assert update_route.call_count == 0
    body = json.loads(confirm_route.calls[0].request.content)
    assert body["deviceToken"] == DEVICE_TOKEN


@respx.mock
async def test_confirm_registers_device_token_only_when_explicitly_enabled() -> None:
    client = _make_client(register_device_token=True)
    confirm_route = respx.post(
        "https://api.domonap.ru/sso-api/Authorization/ConfirmAuthorization"
    ).mock(return_value=_confirmation_response())
    update_route = respx.post(
        "https://api.domonap.ru/sso-api/Authorization/UpdateDeviceToken"
    ).mock(return_value=Response(200, text="ok"))

    try:
        success = await client.confirm_login("1234")
    finally:
        await client.close()

    assert success is True
    assert confirm_route.call_count == 1
    assert update_route.call_count == 1
    auth_body = json.loads(confirm_route.calls[0].request.content)
    update_body = json.loads(update_route.calls[0].request.content)
    assert auth_body["deviceToken"] == DEVICE_TOKEN
    assert update_body == {"deviceToken": DEVICE_TOKEN, "platform": "Android"}
