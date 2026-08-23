from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

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


def _register(router: Router, client: MagicMock) -> None:
    register_menu_handlers(
        router,
        client,
        MagicMock(),
        AccessControl([1]),
        AccessControl([1], default_allow=False),
        CooldownManager(),
    )


class TestMainMenu:
    async def test_cmd_start_is_local_and_action_oriented(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = "access"
        client.refresh_token = None
        client.get_doors = AsyncMock()
        _register(router, client)

        msg = _make_message(user_id=1)
        await router.message.handlers[0].callback(msg)

        client.get_doors.assert_not_awaited()
        text = msg.answer.call_args[0][0]
        keyboard = msg.answer.call_args.kwargs["reply_markup"]
        assert text == "🏠 Домофон\n\nВыберите действие."
        assert any(
            button.text == "🔓 Открыть дверь"
            for row in keyboard.inline_keyboard
            for button in row
        )

    async def test_callback_home_acknowledges_without_remote_request(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = None
        client.refresh_token = None
        client.get_doors = AsyncMock()
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "m:main"

        for handler in router.callback_query.handlers:
            if handler.callback.__name__ == "callback_main_menu":
                await handler.callback(cb)
                break

        client.get_doors.assert_not_awaited()
        cb.answer.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "Domonap не подключён" in text

    async def test_noop_answers(self) -> None:
        router = Router()
        client = MagicMock()
        _register(router, client)

        cb = _make_callback(user_id=1)
        for handler in router.callback_query.handlers:
            if handler.callback.__name__ == "callback_noop":
                await handler.callback(cb)
                break

        cb.answer.assert_awaited_once()
