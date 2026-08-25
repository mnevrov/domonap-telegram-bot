from time import monotonic

_MAX_COOLDOWN_ENTRIES = 2048


class CooldownManager:
    def __init__(self, timeout: float = 5.0) -> None:
        self._cooldowns: dict[tuple[int, str], float] = {}
        self._timeout = timeout

    def is_ready(self, user_id: int, action_id: str) -> bool:
        last = self._cooldowns.get((user_id, action_id))
        if last is None:
            return True
        return monotonic() - last >= self._timeout

    def set(self, user_id: int, action_id: str) -> None:
        key = (user_id, action_id)
        if key not in self._cooldowns and len(self._cooldowns) >= _MAX_COOLDOWN_ENTRIES:
            self.clear_expired()
            if len(self._cooldowns) >= _MAX_COOLDOWN_ENTRIES:
                oldest = min(self._cooldowns, key=self._cooldowns.__getitem__)
                del self._cooldowns[oldest]
        self._cooldowns[key] = monotonic()

    def remaining(self, user_id: int, action_id: str) -> float:
        last = self._cooldowns.get((user_id, action_id))
        if last is None:
            return 0.0
        return max(0.0, self._timeout - (monotonic() - last))

    def clear(self, user_id: int, action_id: str) -> None:
        """Release a failed action so the user can retry immediately."""
        self._cooldowns.pop((user_id, action_id), None)

    def clear_expired(self) -> int:
        now = monotonic()
        expired = [k for k, t in self._cooldowns.items() if now - t >= self._timeout]
        for k in expired:
            del self._cooldowns[k]
        return len(expired)
