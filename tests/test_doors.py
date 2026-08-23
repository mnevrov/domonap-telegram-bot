import json
from unittest.mock import AsyncMock, MagicMock

import respx
from aiogram import Router
from aiogram.types import CallbackQuery, Message, User
from httpx import Response

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.models import DoorKey
from domonap_bot.storage.tokens import TokenStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers
from domonap_bot.telegram.handlers import _auto_open_door
from domonap_bot.telegram.keyboards import (
    door_detail_keyboard,
    door_list_keyboard,
    door_selection_keyboard,
)


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def _make_message(user_id: int) -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = user_id
    message.answer = AsyncMock()
    return message


def _handlers(router: Router) -> dict[str, object]:
    return {handler.callback.__name__: handler.callback for handler in router.callback_query.handlers}


class TestDoorList:
    async def test_door_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(return_value=[])
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"
        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Доступных дверей нет" in text
        cb.answer.assert_awaited_once()

    async def test_door_list_shows_names_only_as_actions(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(
            return_value=[
                DoorKey(id="1", doorId="d1", name="Главный вход"),
                DoorKey(id="2", doorId="d2", name="Калитка"),
            ]
        )
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = "d:p:0"
        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert "Выберите дверь" in text
        assert "Главный вход" not in text
        assert any(
            button.text == "🚪 Главный вход"
            for row in keyboard.inline_keyboard
            for button in row
        )

    async def test_callback_acknowledges_before_loading_doors(self) -> None:
        router = Router()
        client = MagicMock()
        events: list[str] = []

        async def get_doors() -> list[DoorKey]:
            events.append("api")
            return []

        client.get_doors = AsyncMock(side_effect=get_doors)
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)

        async def answer(*args: object, **kwargs: object) -> None:
            events.append("ack")

        cb.answer = AsyncMock(side_effect=answer)
        cb.data = "d:p:0"
        await router.callback_query.handlers[0].callback(cb)

        assert events[:2] == ["ack", "api"]


class TestDoorKeyboards:
    def test_callbacks_use_physical_door_id(self) -> None:
        door = DoorKey(id="key-123", doorId="door-456", name="Главный вход")

        selection = door_selection_keyboard([door])
        listing = door_list_keyboard([door], page=0, total_pages=1)
        detail = door_detail_keyboard(door)

        assert selection.inline_keyboard[0][0].callback_data == "open:door-456"
        assert listing.inline_keyboard[0][0].callback_data == "d:det:door-456"
        assert detail.inline_keyboard[0][0].callback_data == "d:open:door-456"
        assert detail.inline_keyboard[0][0].style == "success"


class TestDoorDetail:
    async def test_door_detail_shows_info(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_doors = AsyncMock(
            return_value=[
                DoorKey(
                    id="key-1",
                    doorId="door-1",
                    name="Главный вход",
                    domofonPublicPin="1234",
                ),
            ]
        )
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = "d:det:door-1"
        await _handlers(router)["callback_door_detail"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Главный вход" in text
        assert "PIN" in text


class TestDoorOpen:
    async def test_door_open_success(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=True)
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"
        await _handlers(router)["callback_door_open"](cb)

        client.open_door.assert_awaited_once_with("door123")
        assert cb.answer.await_args.args[0] == "Открываю…"
        assert "✅ Дверь открыта" in cb.message.edit_text.call_args[0][0]

    async def test_door_open_failure(self) -> None:
        router = Router()
        client = MagicMock()
        client.open_door = AsyncMock(return_value=False)
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = "d:open:door123"
        await _handlers(router)["callback_door_open"](cb)

        assert "❌ Не удалось" in cb.message.edit_text.call_args[0][0]

    @respx.mock
    async def test_keyboard_to_handler_to_http_uses_door_id(self) -> None:
        storage = MagicMock()
        client = DomonapClient(
            token_storage=TokenStorage(storage),
            device_token="00000000-0000-4000-8000-000000000001",
            instance_id="00000000-0000-4000-8000-000000000002",
        )
        client.set_tokens("access", "refresh", "2027-01-01T00:00:00+03:00")

        door = DoorKey(id="key-123", doorId="door-456", name="Главный вход")
        callback_data = door_detail_keyboard(door).inline_keyboard[0][0].callback_data
        assert callback_data == "d:open:door-456"

        route = respx.post("https://api.domonap.ru/client-api/Device/OpenRelayByDoorId").mock(
            return_value=Response(200, text="ok")
        )

        router = Router()
        register_door_handlers(router, client, AccessControl([1]), CooldownManager())

        cb = _make_callback(user_id=1)
        cb.data = callback_data
        await _handlers(router)["callback_door_open"](cb)

        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body == {"doorId": "door-456"}


class TestAutoOpenDoor:
    async def test_single_door_command_uses_physical_door_id(self) -> None:
        door = DoorKey(id="key-123", doorId="door-456", name="Главный вход")
        client = MagicMock()
        client.open_door = AsyncMock(return_value=True)
        cooldown = CooldownManager()
        message = _make_message(user_id=1)

        await _auto_open_door(message, door, 1, client, cooldown)

        client.open_door.assert_awaited_once_with("door-456")
        assert cooldown.is_ready(1, "door-456") is False
