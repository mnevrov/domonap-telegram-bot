from typing import cast

from aiogram.types import CallbackQuery, Message


def editable_callback_message(callback: CallbackQuery) -> Message | None:
    """Return a callback message only when Telegram allows editing it."""
    message = callback.message
    if message is None or not hasattr(message, "edit_text"):
        return None
    return cast(Message, message)
