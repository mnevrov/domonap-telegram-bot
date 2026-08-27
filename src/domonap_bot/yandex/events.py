from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from domonap_bot.domonap.models import IncomingCallPayload
from domonap_bot.yandex.active_call import ActiveCallRegistry
from domonap_bot.yandex.scenario import YandexScenarioAnnouncer

logger = logging.getLogger(__name__)


class LiveEventSource(Protocol):
    def listen_once(self) -> AsyncIterator[IncomingCallPayload]: ...

    async def close(self) -> None: ...


class YandexCallObserver:
    """Apply Yandex-specific state changes only to live SignalR events."""

    def __init__(
        self,
        active_calls: ActiveCallRegistry,
        announcer: YandexScenarioAnnouncer | None = None,
    ) -> None:
        self._active_calls = active_calls
        self._announcer = announcer
        self._announcement_tasks: set[asyncio.Task[None]] = set()

    async def _announce(self, call_id: str, door_id: str) -> None:
        if self._announcer is None:
            return
        await self._announcer.announce(call_id=call_id, door_id=door_id)

    def _schedule_announcement(self, call_id: str, door_id: str) -> None:
        if self._announcer is None:
            return
        task = asyncio.create_task(self._announce(call_id, door_id))
        self._announcement_tasks.add(task)

        def on_done(done: asyncio.Task[None]) -> None:
            self._announcement_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.warning(
                    "Yandex announcement task failed: call_id=%s error=%s",
                    call_id,
                    type(error).__name__,
                )

        task.add_done_callback(on_done)

    async def observe(self, payload: IncomingCallPayload) -> None:
        if payload.event_message == "DomofonCallEnded":
            await self._active_calls.finish(payload.call_id)
            return

        door_id = payload.door_id
        if not door_id:
            logger.warning(
                "Live Domonap call cannot be exposed to Alice: call_id=%s door_id=<missing>",
                payload.call_id,
            )
            return

        # Active-call state is updated before CallWatcher receives the event. The remote
        # Yandex HTTP request is deliberately detached so it cannot delay Telegram.
        await self._active_calls.start(payload.call_id, door_id)
        self._schedule_announcement(payload.call_id, door_id)

    async def disconnect(self) -> None:
        await self._active_calls.clear()

    async def close(self) -> None:
        await self.disconnect()
        tasks = tuple(self._announcement_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._announcement_tasks.clear()


class ObservedCallEventSource:
    """Decorate the SignalR event source without changing CallWatcher polling behavior."""

    def __init__(self, source: LiveEventSource, observer: YandexCallObserver) -> None:
        self._source = source
        self._observer = observer

    async def listen_once(self) -> AsyncIterator[IncomingCallPayload]:
        try:
            async for payload in self._source.listen_once():
                try:
                    await self._observer.observe(payload)
                except Exception:
                    # Yandex integration must never break Telegram call delivery.
                    logger.exception(
                        "Yandex live-call observer failed: call_id=%s",
                        payload.call_id,
                    )
                yield payload
        finally:
            # Once SignalR is not live, current-call state is no longer authoritative.
            await self._observer.disconnect()

    async def close(self) -> None:
        await self._observer.close()
        await self._source.close()
