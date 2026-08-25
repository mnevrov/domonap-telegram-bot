import json
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        ...

    @abstractmethod
    async def get(self, key: str) -> str | None:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def set_user_allowed(self, telegram_id: int) -> None:
        ...

    @abstractmethod
    async def is_user_allowed(self, telegram_id: int) -> bool:
        ...

    @abstractmethod
    async def set_user_admin(self, telegram_id: int) -> None:
        ...

    @abstractmethod
    async def is_user_admin(self, telegram_id: int) -> bool:
        ...

    async def remove_user_admin(self, telegram_id: int) -> None:
        await self.delete(f"access:admin:{telegram_id}")

    @abstractmethod
    async def list_allowed_users(self) -> list[int]:
        ...

    @abstractmethod
    async def list_admin_users(self) -> list[int]:
        ...

    @abstractmethod
    async def remove_user(self, telegram_id: int) -> None:
        ...

    async def set_user_profile(
        self,
        telegram_id: int,
        *,
        first_name: str | None,
        username: str | None,
    ) -> None:
        await self.set(
            f"user:profile:{telegram_id}",
            json.dumps(
                {
                    "first_name": (first_name or "").strip()[:128],
                    "username": (username or "").strip().lstrip("@")[:64],
                },
                ensure_ascii=True,
                separators=(",", ":"),
            ),
        )

    async def get_user_profile(self, telegram_id: int) -> dict[str, str]:
        raw = await self.get(f"user:profile:{telegram_id}")
        if raw is None:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(key): str(item)
            for key, item in value.items()
            if key in {"first_name", "username"} and item
        }
