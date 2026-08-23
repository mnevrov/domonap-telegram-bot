import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from domonap_bot.config import Settings
from domonap_bot.domonap.models import CallLogEntry, DoorKey, IncomingCallPayload
from domonap_bot.telegram.call_watcher import _MAX_SEEN_IDS, CallWatcher


class FailingEventSource:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("signalr down")
        self.attempts = 0
        self.closed = False

    async def listen_once(self) -> AsyncIterator[IncomingCallPayload]:
        self.attempts += 1
        raise self.error
        yield IncomingCallPayload(CallId="unreachable")

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        telegram_bot_token="test:token",
        allowed_telegram_user_ids=[123, 456],
        admin_telegram_user_ids=[],
        call_watcher_enabled=True,
    )


@pytest.fixture
def client() -> MagicMock:
    c = MagicMock()
    c.get_call_logs = AsyncMock(return_value=[])
    c.get_doors = AsyncMock(return_value=[])
    c.refresh_session = AsyncMock(return_value=True)
    return c


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock()
    b.send_photo = AsyncMock()
    return b


@pytest.fixture
def watcher(client: MagicMock, bot: MagicMock, settings: Settings) -> CallWatcher:
    return CallWatcher(client, bot, settings)


@pytest.mark.asyncio(loop_scope="module")
class TestDeduplication:
    async def test_same_call_id_not_sent_twice(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        entry = CallLogEntry(call_id="call_001", answered=False)

        await watcher._handle_entry(entry)
        assert watcher.get_seen_ids_count() == 1
        assert bot.send_message.await_count == 2

        bot.send_message.reset_mock()
        await watcher._handle_entry(entry)
        assert watcher.get_seen_ids_count() == 1
        bot.send_message.assert_not_awaited()

    async def test_multiple_unique_call_ids_all_sent(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        for i in range(5):
            entry = CallLogEntry(call_id=f"call_{i:03d}", answered=False)
            await watcher._handle_entry(entry)

        assert watcher.get_seen_ids_count() == 5
        assert bot.send_message.await_count == 10

    async def test_same_call_id_from_payload_not_sent_twice(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        payload = IncomingCallPayload(CallId="call_001")

        await watcher._handle_payload(payload)
        assert watcher.get_seen_ids_count() == 1
        assert bot.send_message.await_count == 2

        bot.send_message.reset_mock()
        await watcher._handle_payload(payload)
        assert watcher.get_seen_ids_count() == 1
        bot.send_message.assert_not_awaited()

    async def test_entry_and_payload_with_same_id_deduplicated(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        entry = CallLogEntry(call_id="call_001", answered=False)
        payload = IncomingCallPayload(CallId="call_001")

        await watcher._handle_entry(entry)
        bot.send_message.reset_mock()

        await watcher._handle_payload(payload)
        bot.send_message.assert_not_awaited()

    async def test_door_name_in_message(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        watcher._door_map["d1"] = DoorKey(
            id="k1", door_id="d1", name="Main Entrance",
        )
        entry = CallLogEntry(call_id="c1", door_id="d1", answered=False)

        await watcher._handle_entry(entry)

        call_args = bot.send_message.call_args
        text = call_args[1]["text"]
        assert "Main Entrance" in text
        assert "Входящий звонок" in text

    async def test_trim_seen_ids(
        self, watcher: CallWatcher,
    ) -> None:
        for i in range(_MAX_SEEN_IDS + 100):
            watcher._add_seen(f"call_{i:06d}")

        assert watcher.get_seen_ids_count() <= _MAX_SEEN_IDS

    async def test_photo_sent_when_available(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        entry = CallLogEntry(
            call_id="c1",
            answered=False,
            photo_url="https://example.com/photo.jpg",
        )

        await watcher._handle_entry(entry)

        assert bot.send_photo.await_count == 2
        bot.send_message.assert_not_awaited()

    async def test_keyboard_with_door_id(
        self, watcher: CallWatcher,
    ) -> None:
        kb = watcher._build_keyboard(door_id="d1", video_url=None)
        assert kb is not None
        assert kb.inline_keyboard[0][0].callback_data == "open:d1"
        assert kb.inline_keyboard[0][0].text == "🔓 Открыть"

    async def test_keyboard_with_video_url(
        self, watcher: CallWatcher,
    ) -> None:
        kb = watcher._build_keyboard(door_id=None, video_url="https://example.com/video")
        assert kb is not None
        assert kb.inline_keyboard[0][0].url == "https://example.com/video"
        assert kb.inline_keyboard[0][0].text == "📹 Видео"

    async def test_keyboard_with_both(
        self, watcher: CallWatcher,
    ) -> None:
        kb = watcher._build_keyboard(door_id="d1", video_url="https://example.com/video")
        assert kb is not None
        assert len(kb.inline_keyboard) == 2

    async def test_keyboard_no_buttons(
        self, watcher: CallWatcher,
    ) -> None:
        kb = watcher._build_keyboard(door_id=None, video_url=None)
        assert kb is None

    async def test_keyboard_with_call_id(
        self, watcher: CallWatcher,
    ) -> None:
        kb = watcher._build_keyboard(door_id=None, video_url=None, call_id="c1")
        assert kb is not None
        row = kb.inline_keyboard[0]
        assert row[0].callback_data == "answer:c1"
        assert row[0].text == "📞 Ответить"
        assert row[1].callback_data == "reject:c1"
        assert row[1].text == "🔴 Сбросить"

    async def test_handle_entry_notification_includes_call_buttons(
        self, watcher: CallWatcher, bot: MagicMock,
    ) -> None:
        entry = CallLogEntry(call_id="c1", door_id="d1", answered=False)

        await watcher._handle_entry(entry)

        kb = bot.send_message.call_args[1]["reply_markup"]
        callback_datas = {
            btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data
        }
        assert "answer:c1" in callback_datas
        assert "reject:c1" in callback_datas
        assert "open:d1" in callback_datas

    async def test_message_text_with_door(
        self, watcher: CallWatcher,
    ) -> None:
        door = DoorKey(id="k1", door_id="d1", name="Entrance")
        text = watcher._build_message_text(door=door)
        assert "Входящий звонок" in text
        assert "Entrance" in text
        assert "Время" in text

    async def test_message_text_with_address(
        self, watcher: CallWatcher,
    ) -> None:
        text = watcher._build_message_text(address="ул. Ленина, д. 1")
        assert "ул. Ленина, д. 1" in text
        assert "Входящий звонок" in text

    async def test_message_text_with_call_time(
        self, watcher: CallWatcher,
    ) -> None:
        t = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        text = watcher._build_message_text(call_time=t)
        assert "14:30:00" in text

    async def test_message_text_door_takes_precedence(
        self, watcher: CallWatcher,
    ) -> None:
        door = DoorKey(id="k1", door_id="d1", name="Garage")
        text = watcher._build_message_text(door=door, address="ул. Ленина, д. 1")
        assert "Garage" in text
        assert "ул. Ленина" not in text

    async def test_respects_disabled_config(
        self, client: MagicMock, bot: MagicMock,
    ) -> None:
        disabled_settings = Settings(
            telegram_bot_token="test:token",
            allowed_telegram_user_ids=[123],
            admin_telegram_user_ids=[],
            call_watcher_enabled=False,
        )
        w = CallWatcher(client, bot, disabled_settings)
        await w.start()
        assert w._task is None


class TestSignalRRetry:
    async def test_run_retries_signalr_after_bounded_polling(
        self, monkeypatch: pytest.MonkeyPatch, bot: MagicMock, settings: Settings
    ) -> None:
        import domonap_bot.telegram.call_watcher as call_watcher_module

        monkeypatch.setattr(call_watcher_module, "_SIGNALR_RETRY_INTERVAL", 0.01)
        monkeypatch.setattr(call_watcher_module, "_POLL_INTERVAL", 0.01)

        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        client.get_doors = AsyncMock(return_value=[])
        client.refresh_session = AsyncMock(return_value=True)
        source = FailingEventSource()

        watcher = CallWatcher(client, bot, settings, event_source=source)
        run_task = asyncio.create_task(watcher._run())

        async def wait_for_second_attempt() -> None:
            while source.attempts < 2:
                await asyncio.sleep(0)

        try:
            await asyncio.wait_for(wait_for_second_attempt(), timeout=2.0)
        finally:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
            await source.close()

        assert source.attempts >= 2

    async def test_stop_does_not_hang_while_polling(
        self, monkeypatch: pytest.MonkeyPatch, bot: MagicMock, settings: Settings
    ) -> None:
        """Cancellation during polling must propagate and close the event source."""
        import domonap_bot.telegram.call_watcher as call_watcher_module

        monkeypatch.setattr(call_watcher_module, "_POLL_INTERVAL", 10.0)

        client = MagicMock()
        client.get_call_logs = AsyncMock(return_value=[])
        client.get_doors = AsyncMock(return_value=[])
        client.refresh_session = AsyncMock(return_value=True)
        source = FailingEventSource(NotImplementedError("n/a"))

        watcher = CallWatcher(client, bot, settings, event_source=source)
        watcher._task = asyncio.create_task(watcher._run())

        await asyncio.sleep(0.05)
        await asyncio.wait_for(watcher.stop(), timeout=2.0)

        assert source.closed is True
