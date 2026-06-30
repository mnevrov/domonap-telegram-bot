from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import Door


def door_selection_keyboard(doors: list[Door]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d.name, callback_data=f"open:{d.id}")]
        for d in doors
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
