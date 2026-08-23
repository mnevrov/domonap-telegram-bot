from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import (
    _parse_telegram_user_id,
    _pending_removals,
    register_admin_handlers,
)
from domonap_bot.telegram.fsm import AdminStates


def _handlers(storage: MagicMock) -> dict[str, object]:
    router = Router()
    register_admin_handlers(
        router,
        MagicMock(),
        storage,
        AccessControl([1], default_allow=False),
        AccessControl([1]),
    )
    result: dict[str, object] = {}
    for handler in [*router.message.handlers, *router.callback_query.handlers]:
        result[handler.callback.__name__] = handler.callback
    return result


def _message(text: str) -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 1
    message.text = text
    message.answer = AsyncMock()
    return message


def _callback(data: str) -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 1
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def test_user_id_parser_accepts_only_positive_ascii_decimal() -> None:
    assert _parse_telegram_user_id(" 123456789 ") == 123456789
    assert _parse_telegram_user_id("0") is None
    assert _parse_telegram_user_id("-1") is None
    assert _parse_telegram_user_id("²") is None
    assert _parse_telegram_user_id("１２３") is None
    assert _parse_telegram_user_id("1.5") is None


async def test_add_user_rejects_zero_without_storage_write() -> None:
    storage = MagicMock()
    storage.set_user_allowed = AsyncMock()
    handlers = _handlers(storage)
    state = FSMContext(storage=MemoryStorage(), key="add-zero")
    await state.set_state(AdminStates.waiting_user_id)
    message = _message("0")

    await handlers["fsm_add_user_id"](message, state)  # type: ignore[operator]

    storage.set_user_allowed.assert_not_awaited()
    assert "positive numeric" in message.answer.await_args.args[0]
    assert await state.get_state() == AdminStates.waiting_user_id


async def test_grant_admin_rejects_unicode_digit_without_storage_lookup() -> None:
    storage = MagicMock()
    storage.is_user_allowed = AsyncMock()
    storage.set_user_admin = AsyncMock()
    handlers = _handlers(storage)
    state = FSMContext(storage=MemoryStorage(), key="grant-unicode")
    await state.set_state(AdminStates.waiting_grant_admin_id)
    message = _message("²")

    await handlers["fsm_grant_admin_id"](message, state)  # type: ignore[operator]

    storage.is_user_allowed.assert_not_awaited()
    storage.set_user_admin.assert_not_awaited()
    assert "positive numeric" in message.answer.await_args.args[0]


async def test_remove_user_rejects_negative_id_without_confirmation_or_delete() -> None:
    _pending_removals.clear()
    storage = MagicMock()
    storage.remove_user = AsyncMock()
    handlers = _handlers(storage)
    callback = _callback("a:rm:-1")

    await handlers["callback_remove_user"](callback)  # type: ignore[operator]

    storage.remove_user.assert_not_awaited()
    assert _pending_removals == {}
    callback.answer.assert_awaited_once_with("Invalid user ID.", show_alert=True)
