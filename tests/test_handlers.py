from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.handlers import (
    CooldownManager,
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


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


class TestAccessControl:
    def test_empty_allowlist_allows_all(self) -> None:
        ac = AccessControl([])
        assert ac.is_allowed(1) is True
        assert ac.is_allowed(999) is True

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

    def test_admin_default_allow_param(self) -> None:
        ac_regular = AccessControl([])
        assert ac_regular.is_allowed(1) is True

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
    register_handlers(router, client, access, admin_access)
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


class TestAnswerAndEndCall:
    async def test_answer_call_success(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)

        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        client.answer_call.assert_awaited_once_with("call123")
        cb.message.edit_text.assert_awaited_once_with("📞 Call answered.")

    async def test_answer_call_failure_result(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(return_value=False)
        handlers = _build_callback_handlers(client)

        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        cb.message.edit_text.assert_awaited_once_with("❌ Failed to answer call.")

    async def test_answer_call_domonap_error(self) -> None:
        client = MagicMock()
        client.answer_call = AsyncMock(side_effect=ApiError("boom"))
        handlers = _build_callback_handlers(client)

        cb = _make_callback(user_id=1)
        cb.data = "answer:call123"

        await handlers["callback_answer_call"](cb)

        cb.message.edit_text.assert_awaited_once()
        assert "API error" in cb.message.edit_text.call_args[0][0]

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
        cb2.answer.assert_awaited_with(
            cb2.answer.call_args[0][0], show_alert=True
        )

    async def test_end_call_success(self) -> None:
        client = MagicMock()
        client.end_call = AsyncMock(return_value=True)
        handlers = _build_callback_handlers(client)

        cb = _make_callback(user_id=1)
        cb.data = "reject:call123"

        await handlers["callback_end_call"](cb)

        client.end_call.assert_awaited_once_with("call123")
        cb.message.edit_text.assert_awaited_once_with("🔴 Call ended.")

    async def test_end_call_domonap_error(self) -> None:
        client = MagicMock()
        client.end_call = AsyncMock(side_effect=ApiError("boom"))
        handlers = _build_callback_handlers(client)

        cb = _make_callback(user_id=1)
        cb.data = "reject:call123"

        await handlers["callback_end_call"](cb)

        cb.message.edit_text.assert_awaited_once()
        assert "API error" in cb.message.edit_text.call_args[0][0]

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



