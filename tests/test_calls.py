from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, User

from domonap_bot.domonap.models import CallLogEntry, CallLogPage
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


def _handlers(router: Router) -> dict[str, object]:
    return {h.callback.__name__: h.callback for h in router.callback_query.handlers}


class TestCallList:
    async def test_call_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(entries=[], current_page=1, per_page=10, total=0)
        )
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
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(
                entries=[
                    CallLogEntry(
                        callId="call1",
                        doorId="d1",
                        caller="John",
                        callTime=datetime(2024, 1, 1, 14, 30, 0),
                        answered=False,
                    ),
                ],
                current_page=1,
                per_page=10,
                total=1,
            )
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
        assert "John" in text

    async def test_call_list_uses_server_total_for_navigation(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(
                entries=[CallLogEntry(callId="call1", caller="John")],
                current_page=1,
                per_page=10,
                total=25,
            )
        )
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"
        await router.callback_query.handlers[0].callback(cb)

        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        nav_callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        assert "c:p:1" in nav_callbacks
        assert any(button.text == "1/3" for row in keyboard.inline_keyboard for button in row)

    async def test_out_of_range_page_clamps_to_last_server_page(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            side_effect=[
                CallLogPage(entries=[], current_page=99, per_page=10, total=21),
                CallLogPage(
                    entries=[CallLogEntry(callId="last", caller="Last")],
                    current_page=3,
                    per_page=10,
                    total=21,
                ),
            ]
        )
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:98"
        await router.callback_query.handlers[0].callback(cb)

        assert client.get_call_logs_page.await_args_list[0].kwargs["current_page"] == 99
        assert client.get_call_logs_page.await_args_list[1].kwargs["current_page"] == 3
        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert any(button.text == "3/3" for row in keyboard.inline_keyboard for button in row)

    async def test_call_list_filter_toggle(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(entries=[], current_page=1, per_page=10, total=0)
        )
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:f:missed"

        await _handlers(router)["callback_call_filter"](cb)

        assert user_call_filter.get(1) is True
        assert client.get_call_logs_page.await_args.kwargs["missed_calls"] is True


class TestCallDetail:
    async def test_detail_uses_paginated_lookup(self) -> None:
        router = Router()
        client = MagicMock()
        entry = CallLogEntry(callId="deep-call", caller="John", answered=True)
        client.find_call_log = AsyncMock(return_value=entry)
        client.get_doors = AsyncMock(return_value=[])
        access = AccessControl([1])
        cooldown = CooldownManager()
        register_call_handlers(router, client, access, cooldown)

        cb = _make_callback(user_id=1)
        cb.data = "c:det:deep-call"

        await _handlers(router)["callback_call_detail"](cb)

        client.find_call_log.assert_awaited_once_with("deep-call")
        text = cb.message.edit_text.call_args[0][0]
        assert "Call Details" in text
        assert "Answered" in text
