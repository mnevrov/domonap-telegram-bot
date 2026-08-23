from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import _parse_telegram_user_id, register_admin_handlers


def _handlers(storage: MagicMock) -> dict[str, object]:
    router = Router()
    register_admin_handlers(
        router,
        MagicMock(),
        storage,
        AccessControl([1], default_allow=False),
        AccessControl([1]),
    )
    return {
        handler.callback.__name__: handler.callback
        for handler in router.callback_query.handlers
    }


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


async def test_remove_confirmation_rejects_negative_id_without_storage_write() -> None:
    storage = MagicMock()
    storage.remove_user = AsyncMock()
    handlers = _handlers(storage)
    callback = _callback("a:rmc:-1")

    await handlers["callback_remove_user_confirm"](callback)  # type: ignore[operator]

    storage.remove_user.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        "Некорректный пользователь",
        show_alert=True,
    )


async def test_grant_rejects_unicode_digit_without_storage_lookup() -> None:
    storage = MagicMock()
    storage.is_user_allowed = AsyncMock()
    handlers = _handlers(storage)
    callback = _callback("a:grant:²")

    await handlers["callback_grant_admin"](callback)  # type: ignore[operator]

    storage.is_user_allowed.assert_not_awaited()
    callback.answer.assert_awaited_once_with(
        "Некорректный пользователь",
        show_alert=True,
    )
