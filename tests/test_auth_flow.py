from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ForceReply, Message, User

from domonap_bot.telegram.auth_flow import (
    AuthStates,
    mask_phone,
    normalize_sms_code,
    request_sms_code,
    submit_sms_code,
)


def _message(user_id: int = 1, text: str = "") -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = user_id
    message.text = text
    message.answer = AsyncMock()
    message.delete = AsyncMock()
    return message


def _state(key: str) -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=key)


def test_mask_phone_hides_middle_digits() -> None:
    assert mask_phone("+79991234567") == "+799***67"
    assert mask_phone("123") == "123"


def test_sms_code_accepts_only_bounded_ascii_digits() -> None:
    assert normalize_sms_code(" 1234 ") == "1234"
    assert normalize_sms_code("") is None
    assert normalize_sms_code("12 34") is None
    assert normalize_sms_code("１２３４") is None
    assert normalize_sms_code("1" * 13) is None


async def test_request_sms_sets_state_and_force_reply() -> None:
    client = MagicMock()
    client.phone = "+79991234567"
    client.login = AsyncMock(return_value=True)
    message = _message()
    state = _state("request")

    result = await request_sms_code(message, client, state)

    assert result is True
    client.login.assert_awaited_once_with("+79991234567")
    assert await state.get_state() == AuthStates.waiting_sms_code
    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert "+799***67" in text
    assert "+79991234567" not in text
    assert isinstance(markup, ForceReply)


async def test_failed_new_request_clears_stale_sms_state() -> None:
    client = MagicMock()
    client.phone = "+79991234567"
    client.login = AsyncMock(return_value=False)
    message = _message()
    state = _state("stale-request")
    await state.set_state(AuthStates.waiting_sms_code)

    result = await request_sms_code(message, client, state)

    assert result is False
    client.login.assert_awaited_once_with("+79991234567")
    assert await state.get_state() is None


async def test_invalid_reply_is_deleted_keeps_state_and_does_not_call_api() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock()
    message = _message(text="not-a-code")
    state = _state("invalid")
    await state.set_state(AuthStates.waiting_sms_code)

    result = await submit_sms_code(message, client, state, message.text)

    assert result is False
    client.confirm_login.assert_not_awaited()
    message.delete.assert_awaited_once()
    assert await state.get_state() == AuthStates.waiting_sms_code
    assert isinstance(message.answer.await_args.kwargs["reply_markup"], ForceReply)


async def test_valid_reply_is_deleted_and_clears_state_on_success() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(return_value=True)
    message = _message(text="1234")
    state = _state("success")
    await state.set_state(AuthStates.waiting_sms_code)

    result = await submit_sms_code(message, client, state, message.text)

    assert result is True
    client.confirm_login.assert_awaited_once_with("1234")
    message.delete.assert_awaited_once()
    assert await state.get_state() is None
    assert message.answer.await_args.args[0] == "✅ Domonap подключён."


async def test_rejected_code_is_deleted_and_requires_new_auth() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(return_value=False)
    message = _message(text="9999")
    state = _state("rejected")
    await state.set_state(AuthStates.waiting_sms_code)

    result = await submit_sms_code(message, client, state, message.text)

    assert result is False
    message.delete.assert_awaited_once()
    assert await state.get_state() is None
    assert "Запросите новый код" in message.answer.await_args.args[0]
