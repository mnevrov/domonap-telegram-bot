from unittest.mock import AsyncMock

import pytest

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.tokens import TokenStorage
from tests.test_client import FakeStorage


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


async def test_hydrate_from_storage_restores_tokens(storage: FakeStorage) -> None:
    token_storage = TokenStorage(storage)
    await token_storage.save(
        AuthSession(
            access_token="saved_access",
            refresh_token="saved_refresh",
            refresh_expiration_date="2027-01-01T00:00:00+03:00",
            phone="+79991234567",
            device_token="00000000-0000-4000-8000-000000000011",
            instance_id="00000000-0000-4000-8000-000000000012",
        )
    )

    # Simulate a process restart: a brand-new client over the same storage.
    client = DomonapClient(token_storage=TokenStorage(storage))
    assert client.access_token is None

    restored = await client.hydrate_from_storage()

    assert restored is True
    assert client.access_token == "saved_access"
    assert client.refresh_token == "saved_refresh"
    assert client.refresh_expiration_date == "2027-01-01T00:00:00+03:00"
    assert client.phone == "+79991234567"
    assert client.device_token == "00000000-0000-4000-8000-000000000011"
    assert client.instance_id == "00000000-0000-4000-8000-000000000012"
    assert (
        client._http.headers["instanceId"] == "00000000-0000-4000-8000-000000000012;"
    )


async def test_hydrate_from_storage_keeps_configured_phone(storage: FakeStorage) -> None:
    token_storage = TokenStorage(storage)
    await token_storage.save(AuthSession(access_token="a", phone="+79991234567"))

    client = DomonapClient(token_storage=TokenStorage(storage), phone="+70009998877")
    await client.hydrate_from_storage()

    assert client.phone == "+70009998877"


async def test_hydrate_from_storage_registers_device_token_when_enabled(
    storage: FakeStorage,
) -> None:
    token_storage = TokenStorage(storage)
    await token_storage.save(AuthSession(access_token="a", phone="+79991234567"))

    client = DomonapClient(
        token_storage=TokenStorage(storage),
        register_device_token=True,
    )
    client._update_device_token = AsyncMock()

    assert await client.hydrate_from_storage() is True

    client._update_device_token.assert_awaited_once()


async def test_hydrate_from_storage_no_saved_session(storage: FakeStorage) -> None:
    client = DomonapClient(token_storage=TokenStorage(storage))

    restored = await client.hydrate_from_storage()

    assert restored is False
    assert client.access_token is None
