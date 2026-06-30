from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.base import Storage

KEY_TOKEN = "domonap_token"
KEY_REFRESH = "domonap_refresh_token"


class TokenStorage:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def save(self, session: AuthSession) -> None:
        await self._storage.set(KEY_TOKEN, session.token)
        if session.refresh_token:
            await self._storage.set(KEY_REFRESH, session.refresh_token)

    async def load(self) -> str | None:
        return await self._storage.get(KEY_TOKEN)

    async def load_refresh(self) -> str | None:
        return await self._storage.get(KEY_REFRESH)

    async def clear(self) -> None:
        await self._storage.delete(KEY_TOKEN)
        await self._storage.delete(KEY_REFRESH)
