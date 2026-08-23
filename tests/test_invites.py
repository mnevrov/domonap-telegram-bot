import asyncio

from domonap_bot.telegram.invites import InviteManager
from tests.test_client import FakeStorage


async def test_invite_is_stored_hashed_and_consumed_once() -> None:
    storage = FakeStorage()
    token = "A" * 32
    manager = InviteManager(storage, token_factory=lambda: token, clock=lambda: 1000.0)

    invite = await manager.create(created_by=1)

    assert invite.token == token
    serialized = "\n".join(f"{key}={value}" for key, value in storage._data.items())
    assert token not in serialized
    assert await manager.consume(token) is True
    assert await manager.consume(token) is False


async def test_expired_invite_is_rejected_and_removed() -> None:
    storage = FakeStorage()
    now = [1000.0]
    token = "B" * 32
    manager = InviteManager(
        storage,
        ttl_seconds=60,
        token_factory=lambda: token,
        clock=lambda: now[0],
    )
    await manager.create(created_by=1)
    now[0] = 1061.0

    assert await manager.consume(token) is False
    assert storage._data == {}


async def test_concurrent_consumers_cannot_claim_same_invite_twice() -> None:
    storage = FakeStorage()
    token = "C" * 32
    manager = InviteManager(storage, token_factory=lambda: token)
    await manager.create(created_by=1)

    results = await asyncio.gather(manager.consume(token), manager.consume(token))

    assert sorted(results) == [False, True]


async def test_malformed_token_never_touches_storage() -> None:
    storage = FakeStorage()
    manager = InviteManager(storage)

    assert await manager.consume("bad token") is False
    assert storage._data == {}
