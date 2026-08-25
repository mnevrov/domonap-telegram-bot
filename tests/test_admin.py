from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.invites import InviteManager
from tests.test_client import FakeStorage


def _make_callback(user_id: int, data: str) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def _build_admin_router(
    storage: FakeStorage,
    *,
    invites: InviteManager | None = None,
) -> tuple[dict[str, object], AccessControl, AccessControl]:
    router = Router()
    client = MagicMock()
    client.access_token = "access"
    client.refresh_token = None
    admin_access = AccessControl([1], default_allow=False)
    access = AccessControl([1])
    register_admin_handlers(
        router,
        client,
        storage,
        admin_access,
        access,
        invites,
    )
    handlers = {
        handler.callback.__name__: handler.callback
        for handler in router.callback_query.handlers
    }
    return handlers, access, admin_access


class TestAdminPanel:
    async def test_admin_panel_shows_localized_status(self) -> None:
        storage = FakeStorage()
        await storage.set_user_allowed(1)
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:panel")

        await handlers["callback_admin_panel"](cb)

        text = cb.message.edit_text.await_args.args[0]
        assert "⚙️ Управление" in text
        assert "Domonap: ✅ подключён" in text
        assert "Пользователей: 1" in text
        cb.answer.assert_awaited_once()

    async def test_logout_requires_confirmation(self) -> None:
        storage = FakeStorage()
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:logout")

        await handlers["callback_admin_logout"](cb, MagicMock())

        assert "Выйти из Domonap?" in cb.message.edit_text.await_args.args[0]
        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].callback_data == "a:logoutc"

    async def test_admin_panel_blocks_non_admin(self) -> None:
        storage = FakeStorage()
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(99, "a:panel")

        await handlers["callback_admin_panel"](cb)

        cb.answer.assert_awaited_with("Доступ запрещён.", show_alert=True)


class TestInvites:
    async def test_invite_action_generates_one_time_deep_link(self) -> None:
        storage = FakeStorage()
        token = "I" * 32
        invites = InviteManager(storage, token_factory=lambda: token)
        handlers, _, _ = _build_admin_router(storage, invites=invites)
        cb = _make_callback(1, "a:invite")
        bot = MagicMock()
        bot_user = MagicMock()
        bot_user.username = "domonap_test_bot"
        bot.get_me = AsyncMock(return_value=bot_user)

        await handlers["callback_create_invite"](cb, bot)

        text = cb.message.edit_text.await_args.args[0]
        assert f"https://t.me/domonap_test_bot?start=invite_{token}" in text
        assert "одноразовая" in text
        assert "15 минут" in text

    async def test_invite_requires_bot_username(self) -> None:
        storage = FakeStorage()
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:invite")
        bot = MagicMock()
        bot_user = MagicMock()
        bot_user.username = None
        bot.get_me = AsyncMock(return_value=bot_user)

        await handlers["callback_create_invite"](cb, bot)

        assert "deep-link недоступен" in cb.message.edit_text.await_args.args[0]
        assert not any(key.startswith("access:invite:") for key in storage._data)


class TestUserManagement:
    async def test_user_list_opens_user_detail_instead_of_deleting(self) -> None:
        storage = FakeStorage()
        for user_id in (1, 42):
            await storage.set_user_allowed(user_id)
        await storage.set_user_admin(1)
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:users")

        await handlers["callback_user_list"](cb)

        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        }
        assert "a:user:42" in callbacks
        assert "a:rm:42" not in callbacks
        assert "a:invite" in callbacks

    async def test_regular_user_detail_offers_admin_promotion(self) -> None:
        storage = FakeStorage()
        await storage.set_user_allowed(42)
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:user:42")

        await handlers["callback_user_detail"](cb)

        text = cb.message.edit_text.await_args.args[0]
        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert "ID: 42" in text
        assert "Роль: Пользователь" in text
        assert any(
            button.callback_data == "a:grant:42"
            for row in keyboard.inline_keyboard
            for button in row
        )

    async def test_grant_admin_updates_persisted_and_runtime_role(self) -> None:
        storage = FakeStorage()
        await storage.set_user_allowed(42)
        handlers, _, admin_access = _build_admin_router(storage)
        cb = _make_callback(1, "a:grant:42")

        await handlers["callback_grant_admin"](cb)

        assert await storage.is_user_admin(42) is True
        assert admin_access.is_allowed(42) is True
        assert "Администратор" in cb.message.edit_text.await_args.args[0]

    async def test_remove_start_shows_explicit_confirmation(self) -> None:
        storage = FakeStorage()
        await storage.set_user_allowed(42)
        handlers, _, _ = _build_admin_router(storage)
        cb = _make_callback(1, "a:rm:42")

        await handlers["callback_remove_user_start"](cb)

        assert await storage.is_user_allowed(42) is True
        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].callback_data == "a:rmc:42"
        assert keyboard.inline_keyboard[0][0].style == "danger"

    async def test_remove_confirm_revokes_persisted_and_runtime_access(self) -> None:
        storage = FakeStorage()
        await storage.set_user_allowed(42)
        handlers, access, admin_access = _build_admin_router(storage)
        access.add_user(42)
        cb = _make_callback(1, "a:rmc:42")

        await handlers["callback_remove_user_confirm"](cb)

        assert await storage.is_user_allowed(42) is False
        assert access.is_allowed(42) is False
        assert admin_access.is_allowed(42) is False
        assert cb.answer.await_args_list[-1].args[0] == "Пользователь удалён"
