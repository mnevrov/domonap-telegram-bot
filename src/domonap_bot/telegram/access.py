from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from aiogram.types import CallbackQuery, Message

Handler = TypeVar("Handler", bound=Callable[..., Awaitable[Any]])


class AccessControl:
    def __init__(self, allowed_user_ids: list[int], *, default_allow: bool = True) -> None:
        self._allowed = set(allowed_user_ids) if allowed_user_ids else set()
        self._default_allow = default_allow

    def is_allowed(self, user_id: int) -> bool:
        if not self._allowed and self._default_allow:
            return True
        return user_id in self._allowed

    def add_user(self, user_id: int) -> None:
        self._allowed.add(user_id)

    def remove_user(self, user_id: int) -> None:
        self._allowed.discard(user_id)

    def require_access(self, handler: Handler) -> Handler:
        @wraps(handler)
        async def wrapper(event: Message | CallbackQuery, *args: Any, **kwargs: Any) -> Any:
            user_id = event.from_user.id if event.from_user else 0
            if not self.is_allowed(user_id):
                msg = "Access denied."
                if isinstance(event, Message):
                    await event.answer(msg)
                elif isinstance(event, CallbackQuery):
                    await event.answer(msg, show_alert=True)
                return None
            return await handler(event, *args, **kwargs)

        return wrapper  # type: ignore[return-value]
