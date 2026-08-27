from __future__ import annotations

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

        await self._active_calls.start(payload.call_id, door_id)
        if self._announcer is not None:
            await self._announcer.announce(call_id=payload.call_id, door_id=door_id)

    async def disconnect(self) -> None:
        await self._active_calls.clear()


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
        await self._observer.disconnect()
        await self._source.close()
