import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from domonap_bot.storage.base import Storage

_INVITE_KEY_PREFIX = "access:invite:v1:"
_DEFAULT_TTL_SECONDS = 15 * 60
_MAX_TOKEN_LENGTH = 64


def _new_token() -> str:
    return secrets.token_urlsafe(24)


def _token_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_INVITE_KEY_PREFIX}{digest}"


def _valid_token(token: str) -> bool:
    if not 16 <= len(token) <= _MAX_TOKEN_LENGTH:
        return False
    return all(char.isascii() and (char.isalnum() or char in "_-") for char in token)


@dataclass(frozen=True, slots=True)
class Invite:
    token: str
    expires_at: int


class InviteManager:
    """Persist one-time invites without persisting the bearer token itself."""

    def __init__(
        self,
        storage: Storage,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] = _new_token,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._storage = storage
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._token_factory = token_factory
        self._lock = asyncio.Lock()

    async def create(self, *, created_by: int) -> Invite:
        if created_by <= 0:
            raise ValueError("created_by must be positive")

        async with self._lock:
            for _ in range(3):
                token = self._token_factory()
                if not _valid_token(token):
                    raise ValueError("token factory returned an invalid invite token")
                key = _token_key(token)
                if await self._storage.get(key) is not None:
                    continue
                expires_at = int(self._clock()) + self._ttl_seconds
                await self._storage.set(
                    key,
                    json.dumps(
                        {
                            "expires_at": expires_at,
                            "created_by": created_by,
                        },
                        separators=(",", ":"),
                    ),
                )
                return Invite(token=token, expires_at=expires_at)

        raise RuntimeError("failed to allocate a unique invite token")

    async def consume(self, token: str) -> bool:
        if not _valid_token(token):
            return False

        key = _token_key(token)
        async with self._lock:
            raw = await self._storage.get(key)
            if raw is None:
                return False

            try:
                record = json.loads(raw)
                expires_at = int(record["expires_at"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                await self._storage.delete(key)
                return False

            if expires_at < int(self._clock()):
                await self._storage.delete(key)
                return False

            await self._storage.delete(key)
            return True
