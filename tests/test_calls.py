from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

import pytest
from aiogram import Router
from aiogram.types import CallbackQuery, User

from domonap_bot.domonap.models import CallLogEntry
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.calls import register_call_handlers, user_call_filter
from domonap_bot.telegram.cooldown import CooldownManager


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=CallbackQuery)
    cb.message.edit_text = AsyncMock()
    return cb


class TestCallList:
    async def test_call_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Calls" in text
        cb.answer.assert_awaited_once()

    async def test_call_list_shows_entries(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(
            return_value=[
                CallLogEntry(
                    callId="call1",
                    doorId="d1",
                    caller="John",
                    callTime=datetime(2024, 1, 1, 14, 30, 0),
                    answered=False,
                ),
            ]
        )
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"

        await router.callback_query.handlers[0].callback(cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Calls" in text

    async def test_call_list_filter_toggle(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:f:missed"

        # Find the filter handler
        for h in router.callback_query.handlers:
            cb_data_check = getattr(h.callback, "__name__", None)
            if cb_data_check == "callback_call_filter":
                await h.callback(cb)
                break

        assert user_call_filter.get(1) is True
