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

    @abstractmethod
    async def list_allowed_users(self) -> list[int]:
        ...

    @abstractmethod
    async def remove_user(self, telegram_id: int) -> None:
        ...
