from unittest.mock import AsyncMock, MagicMock

from domonap_bot.config import Settings
from domonap_bot.domonap.models import CallLogEntry
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.call_watcher import _MAX_SEEN_IDS, CallWatcher


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="test:token",
        allowed_telegram_user_ids=[100],
        admin_telegram_user_ids=[],
        call_watcher_enabled=True,
    )


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    return bot


def _client() -> MagicMock:
    client = MagicMock()
    client.refresh_session = AsyncMock(return_value=True)
    return client


async def test_watcher_uses_live_access_control_for_recipients() -> None:
    access = AccessControl([100])
    bot = _bot()
    watcher = CallWatcher(_client(), bot, _settings(), access=access)

    await watcher._handle_entry(CallLogEntry(callId="call-1"))
    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [100]

    access.add_user(200)
    bot.send_message.reset_mock()
    await watcher._handle_entry(CallLogEntry(callId="call-2"))
    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [100, 200]

    access.remove_user(100)
    bot.send_message.reset_mock()
    await watcher._handle_entry(CallLogEntry(callId="call-3"))
    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [200]


def test_access_control_user_ids_are_deterministic() -> None:
    access = AccessControl([300, 100, 200])
    assert access.user_ids() == [100, 200, 300]

    access.remove_user(200)
    access.add_user(400)
    assert access.user_ids() == [100, 300, 400]


def test_seen_id_eviction_removes_oldest_entries() -> None:
    watcher = CallWatcher(_client(), _bot(), _settings())

    for i in range(_MAX_SEEN_IDS + 5):
        watcher._add_seen(f"call-{i:04d}")

    assert watcher.get_seen_ids_count() == _MAX_SEEN_IDS
    for i in range(5):
        assert f"call-{i:04d}" not in watcher._seen_ids
    assert "call-0005" in watcher._seen_ids
    assert f"call-{_MAX_SEEN_IDS + 4:04d}" in watcher._seen_ids
