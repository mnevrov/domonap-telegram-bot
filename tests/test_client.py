import httpx
import pytest
import respx
from httpx import Response

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import (
    ApiError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.storage.base import Storage


class FakeStorage(Storage):
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def set_user_allowed(self, telegram_id: int) -> None:
        self._data[f"access:allowed:{telegram_id}"] = "1"

    async def is_user_allowed(self, telegram_id: int) -> bool:
        return self._data.get(f"access:allowed:{telegram_id}") == "1"

    async def list_admin_users(self) -> list[int]:
        result: list[int] = []
        for key, value in self._data.items():
            if key.startswith("access:admin:") and value == "1":
                parts = key.split(":")
                if len(parts) == 3:
                    try:
                        result.append(int(parts[2]))
                    except ValueError:
                        continue
        return result

    async def set_user_admin(self, telegram_id: int) -> None:
        self._data[f"access:admin:{telegram_id}"] = "1"

    async def is_user_admin(self, telegram_id: int) -> bool:
        return self._data.get(f"access:admin:{telegram_id}") == "1"

    async def list_allowed_users(self) -> list[int]:
        result: list[int] = []
        for key, val in self._data.items():
            if key.startswith("access:allowed:") and val == "1":
                parts = key.split(":")
                if len(parts) == 3:
                    try:
                        result.append(int(parts[2]))
                    except ValueError:
                        continue
        return result

    async def remove_user(self, telegram_id: int) -> None:
        self._data.pop(f"access:allowed:{telegram_id}", None)
        self._data.pop(f"access:admin:{telegram_id}", None)


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(fake_storage: FakeStorage) -> DomonapClient:
    from domonap_bot.storage.tokens import TokenStorage

    c = DomonapClient(
        token_storage=TokenStorage(fake_storage),
        phone="+79991234567",
        device_token="00000000-0000-4000-8000-000000000001",
        instance_id="00000000-0000-4000-8000-000000000002",
    )
    c.set_tokens("test_access_token", "test_refresh_token", "2027-01-01T00:00:00+03:00")
    return c


class TestClientGetDoors:
    @respx.mock
    async def test_success(self, client: DomonapClient) -> None:
        route = respx.post("https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType").mock(
            return_value=Response(200, json={
                "results": [
                    {"id": "k1", "doorId": "d1", "name": "Door 1"},
                    {"id": "k2", "doorId": "d2", "name": "Door 2", "domofonPublicPin": "1111"},
                ],
                "currentPage": 1,
                "perPage": 100,
                "total": 2,
            })
        )
        doors = await client.get_doors()
        assert route.called
        assert len(doors) == 2
        assert doors[0].id == "k1"
        assert doors[0].name == "Door 1"
        assert doors[1].domofon_public_pin == "1111"

    @respx.mock
    async def test_unauthorized_triggers_refresh_and_retry(self, client: DomonapClient) -> None:
        paged_url = "https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType"
        refresh_url = "https://api.domonap.ru/sso-api/Authorization/RefreshToken"

        respx.post(paged_url).side_effect = [
            Response(401, json={"error": "unauthorized"}),
            Response(200, json={
                "results": [{"id": "k1", "doorId": "d1", "name": "Door"}],
            }),
        ]
        respx.post(refresh_url).mock(
            return_value=Response(200, json={
                "accessToken": "new_access",
                "refreshToken": "new_refresh",
                "refreshExpirationDate": "2027-06-01T00:00:00+03:00",
            })
        )

        doors = await client.get_doors()
        assert len(doors) == 1
        assert client.access_token == "new_access"
        assert client.refresh_token == "new_refresh"

    @respx.mock
    async def test_no_auth_token_raises(self, client: DomonapClient) -> None:
        client.access_token = None
        with pytest.raises(TokenExpiredError):
            await client.get_doors()


class TestClientResponseSemantics:
    @respx.mock
    async def test_bad_request_does_not_invalidate_session(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType").mock(
            return_value=Response(400, json={"error": "bad request"})
        )

        with pytest.raises(ApiError):
            await client.get_doors()

        assert client.access_token == "test_access_token"
        assert client.refresh_token == "test_refresh_token"
        assert client._refresh_token_invalid is False

    @respx.mock
    async def test_forbidden_does_not_invalidate_session(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType").mock(
            return_value=Response(403, json={"error": "forbidden"})
        )

        with pytest.raises(ApiError):
            await client.get_doors()

        assert client.access_token == "test_access_token"
        assert client.refresh_token == "test_refresh_token"
        assert client._refresh_token_invalid is False

    @respx.mock
    async def test_transport_error_is_mapped_to_network_error(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType").mock(
            side_effect=httpx.ConnectError("boom")
        )

        with pytest.raises(NetworkError):
            await client.get_doors()


class TestSignalRReconnect:
    @respx.mock
    async def test_http_error_triggers_renegotiate_instead_of_terminating(
        self, client: DomonapClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx as httpx_module

        # Speed up the test: skip the real backoff sleep.
        async def no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr("domonap_bot.domonap.client.asyncio.sleep", no_sleep)

        negotiate_route = respx.post(
            "https://api.domonap.ru/notificationHub/negotiate?negotiateVersion=1"
        ).mock(return_value=Response(200, json={"connectionId": "conn-1"}))

        hub_route = respx.get(
            "https://api.domonap.ru/notificationHub?id=conn-1"
        )
        hub_route.side_effect = [
            httpx_module.ConnectError("boom"),
            Response(
                200,
                text='{"type":1,"target":"IncomingCall","arguments":[{"CallId":"c1"}]}\n',
            ),
        ]

        events = []
        async for payload in client.listen_events():
            events.append(payload)
            client._closed = True  # stop after first successful event

        assert negotiate_route.call_count == 2  # re-negotiated after the HTTP error
        assert len(events) == 1
        assert events[0].call_id == "c1"


class TestClientCallLogs:
    @respx.mock
    async def test_success(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/CallLog/GetCallLogs").mock(
            return_value=Response(200, json={
                "results": [
                    {"callId": "c1", "answered": True},
                    {"callId": "c2", "answered": False, "caller": "+70000000000"},
                ],
            })
        )
        logs = await client.get_call_logs()
        assert len(logs) == 2
        assert logs[0].call_id == "c1"
        assert logs[0].answered is True
        assert logs[1].call_id == "c2"
        assert logs[1].answered is False
        assert logs[1].caller == "+70000000000"


class TestClientOpenDoor:
    @respx.mock
    async def test_success(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Device/OpenRelayByDoorId").mock(
            return_value=Response(200, text="ok")
        )
        result = await client.open_door("door_1")
        assert result is True

    @respx.mock
    async def test_api_error(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Device/OpenRelayByDoorId").mock(
            return_value=Response(500, text="internal error")
        )
        with pytest.raises(ApiError):
            await client.open_door("door_1")


class TestClientGetUserKey:
    @respx.mock
    async def test_error_null_is_success(self, client: DomonapClient) -> None:
        respx.post("https://api.domonap.ru/client-api/Key/GetUserKey").mock(
            return_value=Response(
                200,
                json={"id": "k1", "doorId": "d1", "name": "Door", "error": None},
            )
        )

        key = await client.get_user_key("k1")

        assert key is not None
        assert key.id == "k1"
        assert key.door_id == "d1"


class TestClientSessionExpiry:
    @respx.mock
    async def test_expired_refresh_raises(self, client: DomonapClient) -> None:
        client.refresh_expiration_date = "2020-01-01T00:00:00+03:00"
        client._refresh_token_invalid = False

        with pytest.raises(SessionExpiredError):
            await client.get_doors()

    @respx.mock
    async def test_marked_invalid_raises(self, client: DomonapClient) -> None:
        client.mark_session_expired("test expiry")
        with pytest.raises(SessionExpiredError):
            await client.get_doors()


class TestClientRefreshFailure:
    @respx.mock
    async def test_refresh_fails_raises(self, client: DomonapClient) -> None:
        paged_url = "https://api.domonap.ru/client-api/Key/GetPagedKeysByKeysType"
        refresh_url = "https://api.domonap.ru/sso-api/Authorization/RefreshToken"

        respx.post(paged_url).mock(
            return_value=Response(401, json={"error": "unauthorized"})
        )
        respx.post(refresh_url).mock(
            return_value=Response(400, json={"error": "bad request"})
        )

        with pytest.raises(SessionExpiredError):
            await client.get_doors()
        assert client.access_token is None
        assert client.refresh_token is None
        assert client._refresh_token_invalid is True


class TestClientMarkSessionExpired:
    async def test_clear_tokens(self, client: DomonapClient) -> None:
        client.mark_session_expired("testing")
        assert client.access_token is None
        assert client.refresh_token is None
        assert client.refresh_expiration_date is None
        assert client._refresh_token_invalid is True


class TestFetchExternalBytes:
    @respx.mock
    async def test_success(self, client: DomonapClient) -> None:
        respx.get("https://example.com/photo.jpg").mock(
            return_value=Response(
                200, content=b"image_data", headers={"Content-Type": "image/jpeg"}
            )
        )
        result = await client.fetch_external_bytes("https://example.com/photo.jpg")
        assert result["ok"] is True
        assert result["body"] == b"image_data"
        assert result["content_type"] == "image/jpeg"

    @respx.mock
    async def test_not_found(self, client: DomonapClient) -> None:
        respx.get("https://example.com/bad").mock(
            return_value=Response(404)
        )
        result = await client.fetch_external_bytes("https://example.com/bad")
        assert result["ok"] is False

    @respx.mock
    async def test_no_auth_token(self, client: DomonapClient) -> None:
        client.access_token = None
        result = await client.fetch_external_bytes("https://example.com/photo.jpg")
        assert result["ok"] is False
        assert "No access token" in str(result["error"])
