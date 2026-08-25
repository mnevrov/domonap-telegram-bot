from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from domonap_bot.telegram.ui.renderer import edit_text
from domonap_bot.telegram.ui.views import View


async def test_edit_text_ignores_message_is_not_modified() -> None:
    message = MagicMock(spec=Message)
    message.edit_text = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="message is not modified")
    )

    await edit_text(message, View("same"))


async def test_edit_text_raises_unrelated_telegram_errors() -> None:
    message = MagicMock(spec=Message)
    error = TelegramBadRequest(method=MagicMock(), message="message to edit not found")
    message.edit_text = AsyncMock(side_effect=error)

    with pytest.raises(TelegramBadRequest):
        await edit_text(message, View("stale"))
