from domonap_bot.domonap.models import AuthSession
from domonap_bot.storage.base import Storage

KEY_ACCESS_TOKEN = "domonap_access_token"
KEY_REFRESH_TOKEN = "domonap_refresh_token"
KEY_REFRESH_EXPIRATION = "domonap_refresh_expiration"
KEY_DEVICE_TOKEN = "domonap_device_token"
KEY_INSTANCE_ID = "domonap_instance_id"
KEY_PHONE = "domonap_phone"


class TokenStorage:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def save(self, session: AuthSession) -> None:
        if session.access_token:
            await self._storage.set(KEY_ACCESS_TOKEN, session.access_token)
        if session.refresh_token:
            await self._storage.set(KEY_REFRESH_TOKEN, session.refresh_token)
        if session.refresh_expiration_date:
            await self._storage.set(KEY_REFRESH_EXPIRATION, session.refresh_expiration_date)
        if session.device_token:
            await self._storage.set(KEY_DEVICE_TOKEN, session.device_token)
        if session.instance_id:
            await self._storage.set(KEY_INSTANCE_ID, session.instance_id)
        if session.phone:
            await self._storage.set(KEY_PHONE, session.phone)

    async def load(self) -> str | None:
        return await self._storage.get(KEY_ACCESS_TOKEN)

    async def load_full(self) -> AuthSession | None:
        access = await self._storage.get(KEY_ACCESS_TOKEN)
        if not access:
            return None
        return AuthSession(
            access_token=access,
            refresh_token=await self._storage.get(KEY_REFRESH_TOKEN),
            refresh_expiration_date=await self._storage.get(KEY_REFRESH_EXPIRATION),
            device_token=await self._storage.get(KEY_DEVICE_TOKEN) or "",
            instance_id=await self._storage.get(KEY_INSTANCE_ID) or "",
            phone=await self._storage.get(KEY_PHONE) or "",
        )

    async def load_refresh(self) -> str | None:
        return await self._storage.get(KEY_REFRESH_TOKEN)

    async def clear(self) -> None:
        await self._storage.delete(KEY_ACCESS_TOKEN)
        await self._storage.delete(KEY_REFRESH_TOKEN)
        await self._storage.delete(KEY_REFRESH_EXPIRATION)
        await self._storage.delete(KEY_DEVICE_TOKEN)
        await self._storage.delete(KEY_INSTANCE_ID)
        await self._storage.delete(KEY_PHONE)
