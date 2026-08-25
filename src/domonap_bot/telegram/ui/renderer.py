from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from domonap_bot.telegram.ui.views import View


async def acknowledge_callback(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """Stop Telegram's callback spinner before any remote work starts."""
    await callback.answer(text=text, show_alert=show_alert)


async def send_view(message: Message, view: View) -> None:
    await message.answer(view.text, reply_markup=view.keyboard)


async def edit_text(message: Message, view: View) -> None:
    try:
        await message.edit_text(view.text, reply_markup=view.keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def edit_caption(message: Message, view: View) -> None:
    """Render a view into an existing media message without changing its media."""
    try:
        await message.edit_caption(caption=view.text, reply_markup=view.keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def edit_view(message: Message, view: View) -> None:
    """Edit text or caption according to the actual Telegram message shape."""
    if isinstance(message.caption, str):
        await edit_caption(message, view)
    else:
        await edit_text(message, view)


async def edit_markup(
    message: Message,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Update only actions/state on an existing text or media message."""
    try:
        await message.edit_reply_markup(reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
