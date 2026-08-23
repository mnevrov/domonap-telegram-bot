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
    await message.edit_text(view.text, reply_markup=view.keyboard)


async def edit_caption(message: Message, view: View) -> None:
    """Render a view into an existing media message without changing its media."""
    await message.edit_caption(caption=view.text, reply_markup=view.keyboard)


async def edit_markup(
    message: Message,
    keyboard: InlineKeyboardMarkup | None,
) -> None:
    """Update only actions/state on an existing text or media message."""
    await message.edit_reply_markup(reply_markup=keyboard)
