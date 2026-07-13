from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.fsm import AdminStates


@pytest.fixture
def cooldown() -> CooldownManager:
    return CooldownManager()


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def _make_message(user_id: int, text: str = "") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _build_admin_router(storage_mock: MagicMock) -> dict[str, object]:
    router = Router()
    client = MagicMock()
    admin_access = AccessControl([1], default_allow=False)
    register_admin_handlers(router, client, storage_mock, admin_access)
    handlers: dict[str, object] = {}
    for h in router.callback_query.handlers:
        if hasattr(h.callback, "__name__"):
            handlers[h.callback.__name__] = h.callback
    for h in router.message.handlers:
        if hasattr(h.callback, "__name__"):
            handlers[h.callback.__name__] = h.callback
    return handlers


class TestAdminPanel:
    async def test_admin_panel_shows_status(self) -> None:
        storage_mock = MagicMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1, 2])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:panel"

        await handlers["callback_admin_panel"](cb)

        assert "Admin Panel" in cb.message.edit_text.call_args[0][0]
        cb.answer.assert_awaited_once()

    async def test_admin_panel_blocks_non_admin(self) -> None:
        storage_mock = MagicMock()
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=99)
        cb.data = "a:panel"

        await handlers["callback_admin_panel"](cb)

        cb.answer.assert_awaited_with("Access denied.", show_alert=True)


class TestUserList:
    async def test_user_list_shows_users(self) -> None:
        storage_mock = MagicMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1, 42, 100])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:users"

        await handlers["callback_user_list"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "42" in text
        assert "100" in text
        cb.answer.assert_awaited_once()


class TestAddUserFSM:
    async def test_add_user_start_shows_prompt(self) -> None:
        storage_mock = MagicMock()
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:add"
        state = FSMContext(storage=MemoryStorage(), key="test")

        await handlers["callback_add_user_start"](cb, state)

        text = cb.message.edit_text.call_args[0][0]
        assert "user id" in text.lower()
        assert await state.get_state() == AdminStates.waiting_user_id

    async def test_add_user_id_saves(self) -> None:
        storage_mock = MagicMock()
        storage_mock.set_user_allowed = AsyncMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[42])
        handlers = _build_admin_router(storage_mock)

        msg = _make_message(user_id=1, text="42")
        state = FSMContext(storage=MemoryStorage(), key="test")
        await state.set_state(AdminStates.waiting_user_id)

        await handlers["fsm_add_user_id"](msg, state)

        storage_mock.set_user_allowed.assert_awaited_once_with(42)
        msg.answer.assert_awaited()
        assert await state.get_state() is None


class TestRemoveUser:
    async def test_remove_user(self) -> None:
        storage_mock = MagicMock()
        storage_mock.remove_user = AsyncMock()
        storage_mock.list_allowed_users = AsyncMock(return_value=[1])
        handlers = _build_admin_router(storage_mock)

        cb = _make_callback(user_id=1)
        cb.data = "a:rm:42"

        await handlers["callback_remove_user"](cb)

        storage_mock.remove_user.assert_awaited_once_with(42)
        cb.answer.assert_awaited_with("User 42 removed.")
