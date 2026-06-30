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
