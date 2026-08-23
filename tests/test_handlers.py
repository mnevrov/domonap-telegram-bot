from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.handlers import (
    _describe_error,
    _mask_phone,
    register_handlers,
)


def _make_message(user_id: int) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def _incoming_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔓 Открыть",
                    callback_data="open:door1",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📞 Ответить",
                    callback_data="answer:call123",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Сбросить",
                    callback_data="reject:call123",
                    style="danger",
                ),
            ],
        ]
    )


def _make_callback(user_id: int, *, caption: str | None = None) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.text = None if caption is not None else "🔔 Звонок в домофон\n🚪 Главный вход"
    cb.message.caption = caption
    cb.message.reply_markup = _incoming_keyboard()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_caption = AsyncMock()
    return cb


class TestAccessControl:
    def test_empty_allowlist_denies_all_by_default(self) -> None:
        ac = AccessControl([])
        assert ac.is_allowed(1) is False
        assert ac.is_allowed(999) is False

    def test_user_in_allowlist(self) -> None:
        ac = AccessControl([42, 100])
        assert ac.is_allowed(42) is True
        assert ac.is_allowed(100) is True

    def test_user_not_in_allowlist(self) -> None:
        ac = AccessControl([42, 100])
        assert ac.is_allowed(1) is False
        assert ac.is_allowed(0) is False

    def test_empty_allowlist_denies_all_when_default_allow_false(self) -> None:
        ac = AccessControl([], default_allow=False)
        assert ac.is_allowed(1) is False
        assert ac.is_allowed(0) is False

    async def test_require_access_allows_allowed_user(self) -> None:
        ac = AccessControl([1])

        @ac.require_access
        async def handler(event: Message) -> str:
            return "passed"

        msg = _make_message(user_id=1)
        result = await handler(msg)
        assert result == "passed"

    async def test_require_access_blocks_unauthorized_user(self) -> None:
        ac = AccessControl([1])

        @ac.require_access
        async def handler(event: Message) -> str:
            return "passed"

        msg = _make_message(user_id=99)
        result = await handler(msg)
        assert result is None
        msg.answer.assert_awaited_once_with("Access denied.")

    async def test_require_access_with_callback_shows_alert(self) -> None:
        ac = AccessControl([1])

        @ac.require_access
        async def handler(event: CallbackQuery) -> str:
            return "passed"

        cb = _make_callback(user_id=99)
        result = await handler(cb)
        assert result is None
        cb.answer.assert_awaited_once_with("Access denied.", show_alert=True)


class TestDescribeError:
    def test_token_expired(self) -> None:
        msg = _describe_error(TokenExpiredError("no token"))
        assert "expired" in msg

    def test_session_expired(self) -> None:
        msg = _describe_error(SessionExpiredError("gone"))
        assert "expired" in msg

    def test_network_error(self) -> None:
        msg = _describe_error(NetworkError("timeout"))
        assert "Network unavailable" in msg

    def test_generic_api_error(self) -> None:
        msg = _describe_error(DomonapError("something broke"))
        assert "API error" in msg

    def test_unknown_subclass(self) -> None:
        class MyError(DomonapError):
            pass

        msg = _describe_error(MyError("custom"))
        assert "API error" in msg


class TestCallbackDataParsing:
    def test_simple_door_id(self) -> None:
        data = "open:123"
        assert data.removeprefix("open:") == "123"

    def test_door_id_with_underscore(self) -> None:
        data = "open:door_main_entrance"
        assert data.removeprefix("open:") == "door_main_entrance"

    def test_door_id_with_uuid(self) -> None:
        uid = "550e8400-e29b-41d4-a716-446655440000"
        data = f"open:{uid}"
        assert data.removeprefix("open:") == uid


class TestCooldownManager:
    def test_first_call_is_ready(self) -> None:
        cm = CooldownManager(timeout=5)
        assert cm.is_ready(1, "door_1") is True

    def test_immediate_retry_not_ready(self) -> None:
        cm = CooldownManager(timeout=5)
        cm.set(1, "door_1")
        assert cm.is_ready(1, "door_1") is False

    def test_different_user_ready(self) -> None:
        cm = CooldownManager(timeout=5)
        cm.set(1, "door_1")
        assert cm.is_ready(2, "door_1") is True

    def test_different_door_ready(self) -> None:
        cm = CooldownManager(timeout=5)
        cm.set(1, "door_1")
        assert cm.is_ready(1, "door_2") is True

    def test_remaining_time(self) -> None:
        cm = CooldownManager(timeout=5)
        cm.set(1, "door_1")
        remaining = cm.remaining(1, "door_1")
        assert 0.0 < remaining <= 5.0

    def test_zero_remaining_when_not_set(self) -> None:
        cm = CooldownManager(timeout=5)
        assert cm.remaining(1, "door_1") == 0.0

    def test_clear_expired(self) -> None:
        cm = CooldownManager(timeout=0)
        cm.set(1, "door_1")
        cm.set(2, "door_2")
        cleared = cm.clear_expired()
        assert cleared == 2
        assert cm.is_ready(1, "door_1") is True
        assert cm.is_ready(2, "door_2") is True

    def test_not_expired_not_cleared(self) -> None:
        cm = CooldownManager(timeout=60)
        cm.set(1, "door_1")
        cleared = cm.clear_expired()
        assert cleared == 0
        assert cm.is_ready(1, "door_1") is False


class TestAdminAccess:
    def test_empty_admin_list_denies_all(self) -> None:
        ac = AccessControl([], default_allow=False)
        assert ac.is_allowed(1) is False
        assert ac.is_allowed(999) is False

    def test_admin_in_list_allowed(self) -> None:
        ac = AccessControl([42], default_allow=False)
        assert ac.is_allowed(42) is True
        assert ac.is_allowed(1) is False

    def test_admin_default_allow_param_is_false(self) -> None:
        ac_regular = AccessControl([])
        assert ac_regular.is_allowed(1) is False

        ac_admin = AccessControl([], default_allow=False)
        assert ac_admin.is_allowed(1) is False

    async def test_admin_require_access_blocks_non_admin(self) -> None:
        ac = AccessControl([], default_allow=False)

        @ac.require_access
        async def handler(event: Message) -> str:
            return "passed"

        msg = _make_message(user_id=99)
        result = await handler(msg)
        assert result is None
        msg.answer.assert_awaited_once_with("Access denied.")


class TestMaskPhone:
    def test_full_russian_number(self) -> None:
        assert _mask_phone("+79991234567") == "+799***67"

    def test_without_plus(self) -> None:
        assert _mask_phone("89991234567") == "899***67"

    def test_short_number(self) -> None:
        assert _mask_phone("123") == "123"

    def test_empty_string(self) -> None:
        assert _mask_phone("") == ""

    def test_international_number(self) -> None:
        assert _mask_phone("+12025551234") == "+120***34"

    def test_only_digits_short(self) -> None:
        assert _mask_phone("12") == "12"


def _build_callback_handlers(client: MagicMock) -> dict[str, object]:
    router = Router()
    access = AccessControl([1])
    admin_access = AccessControl([1], default_allow=False)
    cooldown = CooldownManager()
    register_handlers(router, client, access, admin_access, cooldown)
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


def _build_message_handlers(client: MagicMock) -> dict[str, object]:
    router = Router()
    access = AccessControl([1])
    admin_access = AccessControl([1], default_allow=False)
    cooldown = CooldownManager()
    register_handlers(router, client, access, admin_access, cooldown)
    return {h.callback.__name__: h.callback for h in router.message.handlers}


class TestAuthSurface:
    def test_import_tokens_command_is_not_registered(self) -> None:
        handlers = _build_message_handlers(MagicMock())
        assert "cmd_import_tokens" not in handlers

    async def test_status_masks_phone_number(self) -> None:
        client = MagicMock()
        client.access_token = "access"
        client.refresh_token = None
        client.has_valid_refresh_token = MagicMock(return_value=False)
        client.get_username = AsyncMock(return_value="user")
        client.phone = "+79991234567"
        handlers = _build_message_handlers(client)

        msg = _make_message(user_id=1)
        msg.text = "/status"
        await handlers["cmd_status"](msg)

        msg.answer.assert_awaited_once()
        text = msg.answer.await_args.args[0]
        assert "+799***67" in text
        assert "+79991234567" not in text
        assert "Authenticated: ✅" in text


class TestAnswerAndEndCall:
    async def test_answer_call_success_updates_text_card_and_actions(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        client.answer_call.assert_awaited_once_with("call123")
        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.await_args.args[0]
        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert "🔔 Звонок в домофон" in text
        assert text.endswith("✅ Звонок принят.")
        assert keyboard.inline_keyboard[0][0].callback_data == "open:door1"
        assert keyboard.inline_keyboard[1][0].text == "✅ Звонок принят"
        assert keyboard.inline_keyboard[1][0].callback_data == "noop"

    async def test_answer_call_success_updates_photo_caption(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)
        cb = _make_callback(
            user_id=1,
            caption="🔔 Звонок в домофон\n🚪 Главный вход",
        )
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        cb.message.edit_caption.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()
        assert cb.message.edit_caption.await_args.kwargs["caption"].endswith(
            "✅ Звонок принят."
        )

    async def test_answer_call_false_preserves_active_actions(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=False)
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = {
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        }
        assert "answer:call123" in callbacks
        assert "reject:call123" in callbacks
        assert cb.message.edit_text.await_args.args[0].endswith(
            "❌ Не удалось ответить на звонок."
        )

    async def test_answer_call_domonap_error_preserves_card_context(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(side_effect=ApiError("boom"))
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.await_args.args[0]
        assert "🔔 Звонок в домофон" in text
        assert "API error" in text

    async def test_answer_call_respects_cooldown(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)

        cb1 = _make_callback(user_id=1)
        cb1.data = "answer:call123"
        await handlers["callback_answer_call"](cb1)

        cb2 = _make_callback(user_id=1)
        cb2.data = "answer:call123"
        await handlers["callback_answer_call"](cb2)

        client.answer_call.assert_awaited_once()
        cb2.answer.assert_awaited_with(cb2.answer.call_args[0][0], show_alert=True)

    async def test_end_call_success_marks_call_finished(self) -> None:
        client = MagicMock()
        client.end_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "reject:call123"

        await handlers["callback_end_call"](cb)

        client.end_call.assert_awaited_once_with("call123")
        text = cb.message.edit_text.await_args.args[0]
        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert text.endswith("🔴 Звонок завершён.")
        assert keyboard.inline_keyboard[1][0].text == "🔴 Звонок завершён"
        assert keyboard.inline_keyboard[1][0].callback_data == "noop"

    async def test_end_call_domonap_error_preserves_card(self) -> None:
        client = MagicMock()
        client.end_call = AsyncMock(side_effect=ApiError("boom"))
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "reject:call123"

        await handlers["callback_end_call"](cb)

        cb.message.edit_text.assert_awaited_once()
        assert "🔔 Звонок в домофон" in cb.message.edit_text.await_args.args[0]
        assert "API error" in cb.message.edit_text.await_args.args[0]

    async def test_open_door_success_marks_only_door_action(self) -> None:
        client = MagicMock()
        client.open_door = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)
        cb = _make_callback(user_id=1)
        cb.data = "open:door1"

        await handlers["callback_open_door"](cb)

        keyboard = cb.message.edit_text.await_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "✅ Открыто"
        assert keyboard.inline_keyboard[0][0].callback_data == "noop"
        assert keyboard.inline_keyboard[1][0].callback_data == "answer:call123"
        assert keyboard.inline_keyboard[1][1].callback_data == "reject:call123"

    async def test_answer_and_reject_have_independent_cooldowns(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=True)
        client.end_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)

        cb_answer = _make_callback(user_id=1)
        cb_answer.data = "answer:call123"
        await handlers["callback_answer_call"](cb_answer)

        cb_reject = _make_callback(user_id=1)
        cb_reject.data = "reject:call123"
        await handlers["callback_end_call"](cb_reject)

        client.answer_call.assert_awaited_once()
        client.end_call.assert_awaited_once()
