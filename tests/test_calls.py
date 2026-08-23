from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import CallbackQuery, Message, User

from domonap_bot.domonap.models import CallLogEntry, CallLogPage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.calls import register_call_handlers
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import call_list_keyboard
from domonap_bot.telegram.navigation import NavigationStore


def _make_callback(user_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


def _handlers(router: Router) -> dict[str, object]:
    return {
        handler.callback.__name__: handler.callback
        for handler in router.callback_query.handlers
    }


def _register(
    router: Router,
    client: MagicMock,
    navigation: NavigationStore | None = None,
) -> NavigationStore:
    nav = navigation or NavigationStore()
    register_call_handlers(
        router,
        client,
        AccessControl([1]),
        CooldownManager(),
        nav,
    )
    return nav


class TestCallList:
    async def test_call_list_empty(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(entries=[], current_page=1, per_page=10, total=0)
        )
        client.get_doors = AsyncMock(return_value=[])
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"
        await _handlers(router)["callback_call_list"](cb)

        text = cb.message.edit_text.call_args[0][0]
        assert "Звонки" in text
        assert "Звонков нет" in text
        cb.answer.assert_awaited_once()

    async def test_call_list_uses_buttons_without_duplicate_rows_in_text(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(
                entries=[
                    CallLogEntry(
                        callId="call1",
                        doorId="d1",
                        caller="Иван",
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
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"
        await _handlers(router)["callback_call_list"](cb)

        text = cb.message.edit_text.call_args[0][0]
        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert "Иван" not in text
        assert any(
            "Иван" in button.text
            for row in keyboard.inline_keyboard
            for button in row
        )

    async def test_call_list_uses_server_total_for_navigation(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(
                entries=[CallLogEntry(callId="call1", caller="Иван")],
                current_page=1,
                per_page=10,
                total=25,
            )
        )
        client.get_doors = AsyncMock(return_value=[])
        nav = _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:0"
        await _handlers(router)["callback_call_list"](cb)

        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]
        assert "c:p:1" in callbacks
        assert nav.get(1).call_page == 0
        assert any(button.text == "1/3" for row in keyboard.inline_keyboard for button in row)

    async def test_out_of_range_page_clamps_and_stores_last_page(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            side_effect=[
                CallLogPage(entries=[], current_page=99, per_page=10, total=21),
                CallLogPage(
                    entries=[CallLogEntry(callId="last", caller="Последний")],
                    current_page=3,
                    per_page=10,
                    total=21,
                ),
            ]
        )
        client.get_doors = AsyncMock(return_value=[])
        nav = _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:p:98"
        await _handlers(router)["callback_call_list"](cb)

        assert client.get_call_logs_page.await_args_list[0].kwargs["current_page"] == 99
        assert client.get_call_logs_page.await_args_list[1].kwargs["current_page"] == 3
        assert nav.get(1).call_page == 2
        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert any(button.text == "3/3" for row in keyboard.inline_keyboard for button in row)

    async def test_filter_buttons_switch_to_opposite_mode(self) -> None:
        entry = CallLogEntry(callId="call", caller="Иван")
        all_keyboard = call_list_keyboard([entry], 0, 1, False)
        missed_keyboard = call_list_keyboard([entry], 0, 1, True)

        all_filter_row = all_keyboard.inline_keyboard[1]
        missed_filter_row = missed_keyboard.inline_keyboard[1]

        assert all_filter_row[0].style == "primary"
        assert all_filter_row[0].callback_data == "noop"
        assert all_filter_row[1].callback_data == "c:f:missed"
        assert missed_filter_row[0].callback_data == "c:f:all"
        assert missed_filter_row[1].style == "primary"
        assert missed_filter_row[1].callback_data == "noop"

    async def test_call_list_acknowledges_before_remote_request(self) -> None:
        router = Router()
        client = MagicMock()
        events: list[str] = []

        async def get_page(**kwargs: object) -> CallLogPage:
            events.append("api")
            return CallLogPage(entries=[], current_page=1, per_page=10, total=0)

        client.get_call_logs_page = AsyncMock(side_effect=get_page)
        client.get_doors = AsyncMock(return_value=[])
        _register(router, client)

        cb = _make_callback(user_id=1)

        async def answer(*args: object, **kwargs: object) -> None:
            events.append("ack")

        cb.answer = AsyncMock(side_effect=answer)
        cb.data = "c:p:0"
        await _handlers(router)["callback_call_list"](cb)

        assert events[:2] == ["ack", "api"]

    async def test_filter_is_stored_without_mutating_callback_data(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(entries=[], current_page=1, per_page=10, total=0)
        )
        client.get_doors = AsyncMock(return_value=[])
        nav = _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:f:missed"
        await _handlers(router)["callback_call_filter"](cb)

        assert cb.data == "c:f:missed"
        assert nav.get(1).call_filter_missed is True
        assert nav.get(1).call_page == 0
        assert client.get_call_logs_page.await_args.kwargs["missed_calls"] is True

    async def test_back_restores_page_and_filter(self) -> None:
        router = Router()
        client = MagicMock()
        client.get_call_logs_page = AsyncMock(
            return_value=CallLogPage(
                entries=[CallLogEntry(callId="call21", caller="Иван")],
                current_page=2,
                per_page=10,
                total=25,
            )
        )
        client.get_doors = AsyncMock(return_value=[])
        nav = NavigationStore()
        nav.set_call_view(1, page=1, missed=True)
        _register(router, client, nav)

        cb = _make_callback(user_id=1)
        cb.data = "c:back"
        await _handlers(router)["callback_call_back"](cb)

        assert client.get_call_logs_page.await_args.kwargs["current_page"] == 2
        assert client.get_call_logs_page.await_args.kwargs["missed_calls"] is True
        assert nav.get(1).call_page == 1
        assert nav.get(1).call_filter_missed is True


class TestCallDetail:
    async def test_detail_uses_paginated_lookup_and_contextual_back(self) -> None:
        router = Router()
        client = MagicMock()
        entry = CallLogEntry(callId="deep-call", caller="Иван", answered=True)
        client.find_call_log = AsyncMock(return_value=entry)
        client.get_doors = AsyncMock(return_value=[])
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:det:deep-call"
        await _handlers(router)["callback_call_detail"](cb)

        client.find_call_log.assert_awaited_once_with("deep-call")
        text = cb.message.edit_text.call_args[0][0]
        keyboard = cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert "Звонок" in text
        assert "Принят" in text
        assert keyboard.inline_keyboard[-1][0].callback_data == "c:back"

    async def test_detail_sends_photo_before_deleting_old_message(self) -> None:
        router = Router()
        client = MagicMock()
        entry = CallLogEntry(
            callId="photo-call",
            caller="Иван",
            answered=True,
            photoUrl="https://example.com/photo.jpg",
        )
        client.find_call_log = AsyncMock(return_value=entry)
        client.get_doors = AsyncMock(return_value=[])
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:det:photo-call"
        cb.message.delete = AsyncMock()

        async def send_photo_before_delete(**kwargs: object) -> None:
            assert cb.message.delete.await_count == 0
            assert kwargs["photo"] == "https://example.com/photo.jpg"

        cb.message.answer_photo = AsyncMock(side_effect=send_photo_before_delete)
        await _handlers(router)["callback_call_detail"](cb)

        cb.message.answer_photo.assert_awaited_once()
        cb.message.delete.assert_awaited_once()
        cb.message.edit_text.assert_not_awaited()

    async def test_detail_photo_failure_falls_back_without_deleting_message(self) -> None:
        router = Router()
        client = MagicMock()
        entry = CallLogEntry(
            callId="broken-photo-call",
            caller="Иван",
            answered=False,
            photoUrl="https://example.com/broken.jpg",
        )
        client.find_call_log = AsyncMock(return_value=entry)
        client.get_doors = AsyncMock(return_value=[])
        _register(router, client)

        cb = _make_callback(user_id=1)
        cb.data = "c:det:broken-photo-call"
        cb.message.answer_photo = AsyncMock(side_effect=RuntimeError("media unavailable"))
        cb.message.delete = AsyncMock()
        await _handlers(router)["callback_call_detail"](cb)

        cb.message.answer_photo.assert_awaited_once()
        cb.message.delete.assert_not_awaited()
        cb.message.edit_text.assert_awaited_once()
        text = cb.message.edit_text.call_args[0][0]
        assert "Звонок" in text
        assert "Пропущен" in text
