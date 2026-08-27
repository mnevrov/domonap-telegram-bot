import pytest

from domonap_bot.yandex.active_call import ActiveCallRegistry


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _registry(clock: Clock) -> ActiveCallRegistry:
    return ActiveCallRegistry(ttl_seconds=60.0, clock=clock)


@pytest.mark.asyncio
async def test_claim_complete_allows_only_one_open() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")

    claimed = await registry.claim_openable()
    assert claimed is not None
    assert claimed.call_id == "call-1"
    assert claimed.door_id == "door-1"
    assert await registry.claim_openable() is None

    await registry.complete("call-1")
    assert await registry.claim_openable() is None
    assert await registry.openable_count() == 0


@pytest.mark.asyncio
async def test_failed_open_can_be_released_while_call_is_live() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")

    first = await registry.claim_openable()
    assert first is not None
    await registry.release(first.call_id)

    second = await registry.claim_openable()
    assert second == first


@pytest.mark.asyncio
async def test_expired_call_fails_closed() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")

    clock.now += 61.0

    assert await registry.claim_openable() is None
    assert await registry.openable_count() == 0


@pytest.mark.asyncio
async def test_end_event_revokes_call() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")

    await registry.finish("call-1")

    assert await registry.claim_openable() is None


@pytest.mark.asyncio
async def test_signalr_disconnect_clear_revokes_all_calls() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")

    await registry.clear()

    assert await registry.claim_openable() is None


@pytest.mark.asyncio
async def test_multiple_live_calls_are_ambiguous_and_fail_closed() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")
    await registry.start("call-2", "door-2")

    assert await registry.claim_openable() is None
    assert await registry.openable_count() == 2


@pytest.mark.asyncio
async def test_duplicate_live_event_does_not_rearm_consumed_call() -> None:
    clock = Clock()
    registry = _registry(clock)
    await registry.start("call-1", "door-1")
    claimed = await registry.claim_openable()
    assert claimed is not None
    await registry.complete("call-1")

    await registry.start("call-1", "door-1")

    assert await registry.claim_openable() is None
