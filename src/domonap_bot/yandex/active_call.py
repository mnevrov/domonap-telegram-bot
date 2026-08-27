from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ClaimedCall:
    call_id: str
    door_id: str


@dataclass
class _ActiveCall:
    call_id: str
    door_id: str
    expires_at: float
    claimed: bool = False
    consumed: bool = False


class ActiveCallRegistry:
    """Track live SignalR calls that may be opened exactly once.

    Polling call-log entries must never be inserted here. All state transitions are
    protected by one asyncio lock because Smart Home requests may race with SignalR
    start/end events in the same process.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._calls: dict[str, _ActiveCall] = {}
        self._lock = asyncio.Lock()

    def _prune_locked(self) -> None:
        now = self._clock()
        expired = [call_id for call_id, call in self._calls.items() if call.expires_at <= now]
        for call_id in expired:
            self._calls.pop(call_id, None)

    async def start(self, call_id: str, door_id: str) -> None:
        if not call_id or not door_id:
            return
        async with self._lock:
            self._prune_locked()
            existing = self._calls.get(call_id)
            if existing is not None:
                # Duplicate live events must not re-arm a call that was already consumed.
                if existing.consumed:
                    return
                existing.door_id = door_id
                existing.expires_at = self._clock() + self._ttl_seconds
                return
            self._calls[call_id] = _ActiveCall(
                call_id=call_id,
                door_id=door_id,
                expires_at=self._clock() + self._ttl_seconds,
            )

    async def finish(self, call_id: str) -> None:
        async with self._lock:
            self._calls.pop(call_id, None)

    async def clear(self) -> None:
        """Fail closed when the live SignalR session is no longer trustworthy."""
        async with self._lock:
            self._calls.clear()

    async def claim_openable(self) -> ClaimedCall | None:
        """Atomically claim the only eligible live call.

        Returns None when there is no call or when multiple calls are simultaneously
        eligible. A claimed call is hidden from other concurrent open attempts until it
        is either completed or released.
        """
        async with self._lock:
            self._prune_locked()
            eligible = [
                call
                for call in self._calls.values()
                if not call.claimed and not call.consumed
            ]
            if len(eligible) != 1:
                return None
            call = eligible[0]
            call.claimed = True
            return ClaimedCall(call_id=call.call_id, door_id=call.door_id)

    async def release(self, call_id: str) -> None:
        """Release a failed open attempt while the same live call is still valid."""
        async with self._lock:
            self._prune_locked()
            call = self._calls.get(call_id)
            if call is not None and not call.consumed:
                call.claimed = False

    async def complete(self, call_id: str) -> None:
        """Consume a successfully handled live call so it cannot open twice."""
        async with self._lock:
            self._prune_locked()
            call = self._calls.get(call_id)
            if call is not None:
                call.claimed = False
                call.consumed = True

    async def has_openable_call(self) -> bool:
        async with self._lock:
            self._prune_locked()
            eligible = [
                call
                for call in self._calls.values()
                if not call.claimed and not call.consumed
            ]
            return len(eligible) == 1

    async def openable_count(self) -> int:
        async with self._lock:
            self._prune_locked()
            return sum(
                1
                for call in self._calls.values()
                if not call.claimed and not call.consumed
            )
