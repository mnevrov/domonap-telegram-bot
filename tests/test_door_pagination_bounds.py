from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers


def _callback(data: str) -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.data = data
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 1
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def _door_list_handler(doors: list[DoorKey]) -> tuple[object, MagicMock]:
    router = Router()
    client = MagicMock()
    client.get_doors = AsyncMock(return_value=doors)
    register_door_handlers(router, client, AccessControl([1]), CooldownManager())
    return router.callback_query.handlers[0].callback, client


def _doors(count: int) -> list[DoorKey]:
    return [
        DoorKey(id=f"key-{index}", doorId=f"door-{index}", name=f"Door {index}")
        for index in range(1, count + 1)
    ]


def _button_texts(callback: MagicMock) -> list[str]:
    keyboard = callback.message.edit_text.await_args.kwargs["reply_markup"]
    return [button.text for row in keyboard.inline_keyboard for button in row]


async def test_negative_page_is_clamped_to_first_page() -> None:
    handler, _client = _door_list_handler(_doors(11))
    callback = _callback("d:p:-1")

    await handler(callback)  # type: ignore[operator]

    buttons = _button_texts(callback)
    assert "🔓 Door 1" in buttons
    assert "🔓 Door 11" not in buttons
    assert "1/2" in buttons


async def test_out_of_range_page_is_clamped_to_last_page() -> None:
    handler, _client = _door_list_handler(_doors(11))
    callback = _callback("d:p:999")

    await handler(callback)  # type: ignore[operator]

    buttons = _button_texts(callback)
    assert "🔓 Door 11" in buttons
    assert "🔓 Door 1" not in buttons
    assert "2/2" in buttons
