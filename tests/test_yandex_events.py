import asyncio
from collections.abc import AsyncIterator

import pytest

from domonap_bot.domonap.models import IncomingCallPayload
from domonap_bot.yandex.active_call import ActiveCallRegistry
from domonap_bot.yandex.events import ObservedCallEventSource, YandexCallObserver


class FakeAnnouncer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def announce(self, *, call_id: str, door_id: str) -> bool:
        self.calls.append((call_id, door_id))
        return True


class BlockingAnnouncer(FakeAnnouncer):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def announce(self, *, call_id: str, door_id: str) -> bool:
        self.calls.append((call_id, door_id))
        self.started.set()
        await self.release.wait()
        return True


class FakeSource:
    def __init__(self, events: list[IncomingCallPayload]) -> None:
        self.events = events
        self.closed = False

    async def listen_once(self) -> AsyncIterator[IncomingCallPayload]:
        for event in self.events:
            yield event

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_live_start_and_end_update_registry_and_announce_once() -> None:
    registry = ActiveCallRegistry()
    announcer = FakeAnnouncer()
    observer = YandexCallObserver(registry, announcer)  # type: ignore[arg-type]

    await observer.observe(
        IncomingCallPayload.model_validate(
            {"CallId": "call-1", "DoorId": "door-1", "EventMessage": "DomofonCallStarted"}
        )
    )
    await asyncio.sleep(0)
    assert await registry.openable_count() == 1
    assert announcer.calls == [("call-1", "door-1")]

    await observer.observe(
        IncomingCallPayload.model_validate(
            {"CallId": "call-1", "DoorId": "door-1", "EventMessage": "DomofonCallEnded"}
        )
    )
    assert await registry.openable_count() == 0
    await observer.close()


@pytest.mark.asyncio
async def test_source_completion_clears_active_calls_fail_closed() -> None:
    registry = ActiveCallRegistry()
    announcer = FakeAnnouncer()
    event = IncomingCallPayload.model_validate(
        {"CallId": "call-1", "DoorId": "door-1", "EventMessage": "DomofonCallStarted"}
    )
    source = FakeSource([event])
    observer = YandexCallObserver(registry, announcer)  # type: ignore[arg-type]
    observed = ObservedCallEventSource(source, observer)

    received = [item async for item in observed.listen_once()]
    await asyncio.sleep(0)

    assert received == [event]
    assert await registry.openable_count() == 0
    assert announcer.calls == [("call-1", "door-1")]
    await observer.close()


@pytest.mark.asyncio
async def test_slow_yandex_announcement_does_not_block_live_event_delivery() -> None:
    registry = ActiveCallRegistry()
    announcer = BlockingAnnouncer()
    event = IncomingCallPayload.model_validate(
        {"CallId": "call-1", "DoorId": "door-1", "EventMessage": "DomofonCallStarted"}
    )
    source = FakeSource([event])
    observer = YandexCallObserver(registry, announcer)  # type: ignore[arg-type]
    observed = ObservedCallEventSource(source, observer)

    received = [item async for item in observed.listen_once()]
    await asyncio.wait_for(announcer.started.wait(), timeout=0.1)

    assert received == [event]
    assert announcer.release.is_set() is False
    await observer.close()


@pytest.mark.asyncio
async def test_missing_door_never_creates_openable_call() -> None:
    registry = ActiveCallRegistry()
    announcer = FakeAnnouncer()
    observer = YandexCallObserver(registry, announcer)  # type: ignore[arg-type]

    await observer.observe(
        IncomingCallPayload.model_validate(
            {"CallId": "call-1", "EventMessage": "DomofonCallStarted"}
        )
    )

    assert await registry.openable_count() == 0
    assert announcer.calls == []
    await observer.close()
