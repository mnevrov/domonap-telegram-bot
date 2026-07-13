from unittest.mock import AsyncMock, MagicMock, PropertyMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.menu import register_menu_handlers


def _make_message(user_id: int) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


class TestMainMenu:
    async def test_cmd_start_shows_menu(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        msg = _make_message(user_id=1)
        await router.message.handlers[0].callback(msg)

        text = msg.answer.call_args[0][0]
        assert "Domonap" in text

    async def test_callback_main_menu(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "m:main"

        for h in router.callback_query.handlers:
            if hasattr(h.callback, "__name__") and h.callback.__name__ == "callback_main_menu":
                await h.callback(cb)
                break

        text = cb.message.edit_text.call_args[0][0]
        assert "Domonap" in text
        cb.answer.assert_awaited_once()

    async def test_noop_answers(self) -> None:
        router = Router()
        client = MagicMock()
        storage = MagicMock()
        access = AccessControl([1])
        admin_access = AccessControl([1], default_allow=False)
        cooldown = CooldownManager()

        register_menu_handlers(router, client, storage, access, admin_access, cooldown)

        cb = _make_callback(user_id=1)
        for h in router.callback_query.handlers:
            if hasattr(h.callback, "__name__") and h.callback.__name__ == "callback_noop":
                await h.callback(cb)
                break

        cb.answer.assert_awaited_once()
