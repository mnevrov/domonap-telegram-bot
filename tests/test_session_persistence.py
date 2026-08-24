import asyncio

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.models import AuthSession
from domonap_bot.main import _bind_session_invalidation_persistence
from domonap_bot.storage.tokens import TokenStorage
from tests.test_client import FakeStorage


async def test_terminal_session_invalidation_is_removed_from_storage() -> None:
    storage = FakeStorage()
    token_storage = TokenStorage(storage)
    await token_storage.save(
        AuthSession(
            access_token="saved-access",
            refresh_token="saved-refresh",
            refresh_expiration_date="2027-01-01T00:00:00+00:00",
        )
    )
    client = DomonapClient(token_storage)
    await client.hydrate_from_storage()

    pending: set[asyncio.Task[None]] = set()
    _bind_session_invalidation_persistence(client, token_storage, pending)

    client.mark_session_expired("test rejection")
    if pending:
        await asyncio.gather(*tuple(pending))

    assert client.access_token is None
    assert client.refresh_token is None
    assert await token_storage.load_full() is None
