from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, User

from domonap_bot.domonap.exceptions import ApiError, NetworkError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.handlers import register_handlers


def _build_handler(client: MagicMock) -> object:
    router = Router()
    register_handlers(
        router,
        client,
        AccessControl([1]),
        AccessControl([1], default_allow=False),
        CooldownManager(),
    )
    handlers = {handler.callback.__name__: handler.callback for handler in router.message.handlers}
    return handlers["cmd_code"]


def _message(text: str) -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 1
    message.text = text
    message.answer = AsyncMock()
    message.delete = AsyncMock()
    return message


def _state(key: str) -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=key)


async def test_code_message_deleted_after_success() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(return_value=True)
    handler = _build_handler(client)
    message = _message("/code 123456")

    await handler(message, _state("success"))  # type: ignore[operator]

    client.confirm_login.assert_awaited_once_with("123456")
    message.delete.assert_awaited_once()
    assert message.answer.await_args.args[0] == "✅ Domonap подключён."


async def test_code_message_deleted_after_network_error() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(side_effect=NetworkError("offline"))
    handler = _build_handler(client)
    message = _message("/code 123456")

    await handler(message, _state("network"))  # type: ignore[operator]

    message.delete.assert_awaited_once()
    assert "Сеть недоступна" in message.answer.await_args.args[0]


async def test_code_message_deleted_after_api_error() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(side_effect=ApiError("invalid code"))
    handler = _build_handler(client)
    message = _message("/code 123456")

    await handler(message, _state("api"))  # type: ignore[operator]

    message.delete.assert_awaited_once()
    assert "Ошибка Domonap API" in message.answer.await_args.args[0]


async def test_delete_failure_does_not_mask_success() -> None:
    client = MagicMock()
    client.confirm_login = AsyncMock(return_value=True)
    handler = _build_handler(client)
    message = _message("/code 123456")
    message.delete = AsyncMock(side_effect=RuntimeError("cannot delete"))

    await handler(message, _state("delete-failure"))  # type: ignore[operator]

    message.delete.assert_awaited_once()
    assert message.answer.await_args.args[0] == "✅ Domonap подключён."
