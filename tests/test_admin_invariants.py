from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, User
from pydantic import ValidationError

from domonap_bot.config import Settings
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.bot import build_bot
from tests.test_client import FakeStorage


def _message(user_id: int) -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = user_id
    message.answer = AsyncMock()
    return message


def _callback(user_id: int, data: str) -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = user_id
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    return callback


def _admin_handlers(
    storage: FakeStorage,
    admin_access: AccessControl,
    access: AccessControl,
) -> dict[str, object]:
    router = Router()
    register_admin_handlers(router, MagicMock(), storage, admin_access, access)
    return {
        handler.callback.__name__: handler.callback
        for handler in router.callback_query.handlers
    }


def test_configured_admin_must_also_be_allowed() -> None:
    with pytest.raises(ValidationError, match="must be a subset"):
        Settings(
            telegram_bot_token="123456:TEST-TOKEN",
            allowed_telegram_user_ids=[1],
            admin_telegram_user_ids=[2],
        )


async def test_configured_admin_is_active_when_allowed() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[1],
        admin_telegram_user_ids=[1],
    )
    client = MagicMock()
    client.phone = ""

    bot, dp = await build_bot(settings, client)
    try:
        router = dp.sub_routers[0]
        handlers = {
            handler.callback.__name__: handler.callback
            for handler in router.message.handlers
        }
        message = _message(1)
        message.text = "/auth"
        state = FSMContext(storage=MemoryStorage(), key="configured-admin")

        await handlers["cmd_auth"](message, state)

        message.answer.assert_awaited_once_with(
            "Номер телефона Domonap не настроен."
        )
    finally:
        await bot.session.close()


async def test_cannot_remove_last_runtime_admin() -> None:
    storage = FakeStorage()
    await storage.set_user_allowed(1)
    await storage.set_user_admin(1)
    access = AccessControl([1])
    admin_access = AccessControl([1])
    handlers = _admin_handlers(storage, admin_access, access)
    callback = _callback(1, "a:rmc:1")

    await handlers["callback_remove_user_confirm"](callback)

    assert await storage.is_user_allowed(1) is True
    assert access.is_allowed(1) is True
    assert admin_access.is_allowed(1) is True
    assert callback.answer.await_args_list[-1].args[0] == "Нельзя удалить последнего администратора"
    assert callback.answer.await_args_list[-1].kwargs == {"show_alert": True}


async def test_can_remove_admin_when_another_admin_remains() -> None:
    storage = FakeStorage()
    for uid in (1, 2):
        await storage.set_user_allowed(uid)
        await storage.set_user_admin(uid)
    access = AccessControl([1, 2])
    admin_access = AccessControl([1, 2])
    handlers = _admin_handlers(storage, admin_access, access)
    callback = _callback(1, "a:rmc:2")

    await handlers["callback_remove_user_confirm"](callback)

    assert await storage.is_user_allowed(2) is False
    assert access.is_allowed(2) is False
    assert admin_access.is_allowed(2) is False
    assert admin_access.is_allowed(1) is True


async def test_cannot_revoke_last_admin_role() -> None:
    storage = FakeStorage()
    await storage.set_user_allowed(1)
    await storage.set_user_admin(1)
    access = AccessControl([1])
    admin_access = AccessControl([1])
    handlers = _admin_handlers(storage, admin_access, access)
    callback = _callback(1, "a:revc:1")

    await handlers["callback_revoke_admin_confirm"](callback)

    assert await storage.is_user_admin(1) is True
    assert admin_access.is_allowed(1) is True
    assert callback.answer.await_args.args[0] == "Нельзя снять права у последнего администратора"
