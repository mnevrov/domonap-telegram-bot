from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domonap_bot.domonap.models import DoorKey


def door_selection_keyboard(doors: list[DoorKey]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d.name, callback_data=f"open:{d.id}")]
        for d in doors
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
