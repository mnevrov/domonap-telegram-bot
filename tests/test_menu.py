from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.invites import InviteManager
from domonap_bot.telegram.menu import register_menu_handlers
from tests.test_client import FakeStorage


def _make_message(user_id: int, text: str = "/start") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.text = text
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


def _register(
    router: Router,
    client: MagicMock,
    *,
    storage: FakeStorage | None = None,
    access: AccessControl | None = None,
    invites: InviteManager | None = None,
) -> tuple[FakeStorage, AccessControl, InviteManager]:
    actual_storage = storage or FakeStorage()
    actual_access = access or AccessControl([1])
    actual_invites = invites or InviteManager(actual_storage)
    register_menu_handlers(
        router,
        client,
        actual_storage,
        actual_access,
        AccessControl([1], default_allow=False),
        CooldownManager(),
        actual_invites,
    )
    return actual_storage, actual_access, actual_invites


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

    async def test_valid_invite_grants_regular_access_once(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = "access"
        client.refresh_token = None
        storage = FakeStorage()
        access = AccessControl([1])
        token = "A" * 32
        invites = InviteManager(storage, token_factory=lambda: token)
        await invites.create(created_by=1)
        _register(router, client, storage=storage, access=access, invites=invites)

        msg = _make_message(user_id=42, text=f"/start invite_{token}")
        await router.message.handlers[0].callback(msg)

        assert await storage.is_user_allowed(42) is True
        assert access.is_allowed(42) is True
        assert "Доступ активирован" in msg.answer.await_args.args[0]
        assert await invites.consume(token) is False

    async def test_invalid_invite_does_not_grant_access(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = None
        client.refresh_token = None
        storage, access, _ = _register(router, client)

        msg = _make_message(user_id=42, text=f"/start invite_{'Z' * 32}")
        await router.message.handlers[0].callback(msg)

        assert await storage.is_user_allowed(42) is False
        assert access.is_allowed(42) is False
        assert "недействительно" in msg.answer.await_args.args[0]

    async def test_existing_user_does_not_consume_invite(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = "access"
        client.refresh_token = None
        storage = FakeStorage()
        access = AccessControl([1])
        token = "B" * 32
        invites = InviteManager(storage, token_factory=lambda: token)
        await invites.create(created_by=1)
        _register(router, client, storage=storage, access=access, invites=invites)

        msg = _make_message(user_id=1, text=f"/start invite_{token}")
        await router.message.handlers[0].callback(msg)

        assert await invites.consume(token) is True

    async def test_unknown_user_without_invite_is_denied(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = None
        client.refresh_token = None
        _register(router, client)

        msg = _make_message(user_id=42)
        await router.message.handlers[0].callback(msg)

        assert "Доступ к боту не разрешён." in msg.answer.await_args.args[0]
        assert "приглашению" in msg.answer.await_args.args[0]

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

    async def test_unconnected_home_does_not_offer_unavailable_actions(self) -> None:
        router = Router()
        client = MagicMock()
        client.access_token = None
        client.refresh_token = None
        _register(router, client)

        msg = _make_message(user_id=1)
        await router.message.handlers[0].callback(msg)

        keyboard = msg.answer.call_args.kwargs["reply_markup"]
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        assert "d:p:0" not in callbacks
        assert "c:p:0" not in callbacks

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
