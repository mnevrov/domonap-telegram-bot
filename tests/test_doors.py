from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, User

from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=CallbackQuery)
    cb.message.edit_text = AsyncMock()
    return cb


def _handlers(router: Router) -> dict[str, object]:
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


class TestDoorList:
    async def test_door_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "No doors" in text
        cb.answer.assert_awaited_once()

    async def test_door_list_shows_doors(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[
            DoorKey(id="1", doorId="d1", name="Main"),
            DoorKey(id="2", doorId="d2", name="Back"),
        ])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Main" in text
        assert "Back" in text


class TestDoorDetail:
    async def test_door_detail_shows_info(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[
            DoorKey(id="1", doorId="d1", name="Main", domofonPublicPin="1234"),
        ])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:det:1"

        h = _handlers(router)
        await h["callback_door_detail"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Main" in text
        assert "PIN" in text


class TestDoorOpen:
    async def test_door_open_success(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=True)
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"

        h = _handlers(router)
        await h["callback_door_open"](cb)

        client.open_door.assert_awaited_once_with("door123")
        cb.message.edit_text.assert_awaited()
        assert "✅" in cb.message.edit_text.call_args[0][0]

    async def test_door_open_failure(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=False)
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_door_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"

        h = _handlers(router)
        await h["callback_door_open"](cb)

        assert "❌" in cb.message.edit_text.call_args[0][0]
