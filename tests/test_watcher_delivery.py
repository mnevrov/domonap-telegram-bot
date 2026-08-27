from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage

from domonap_bot.config import Settings
from domonap_bot.telegram.call_watcher import CallWatcher


def _watcher(bot: MagicMock) -> CallWatcher:
    client = MagicMock()
    client.refresh_session = AsyncMock(return_value=True)
    client.download_media = AsyncMock(return_value=b"photo-bytes")
    settings = Settings(
        telegram_bot_token="test:token",
        allowed_telegram_user_ids=[1, 2],
    )
    return CallWatcher(client, bot, settings)


def _method(chat_id: int = 1) -> SendMessage:
    return SendMessage(chat_id=chat_id, text="notification")


async def test_transient_network_error_is_retried() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=[
            TelegramNetworkError(method=_method(), message="temporary network failure"),
            None,
        ]
    )
    bot.send_photo = AsyncMock()
    watcher = _watcher(bot)

    with patch(
        "domonap_bot.telegram.call_watcher.asyncio.sleep",
        new=AsyncMock(),
    ) as sleep:
        await watcher._send_notification([1], "hello")

    assert bot.send_message.await_count == 2
    sleep.assert_awaited_once_with(0.5)


async def test_short_retry_after_is_respected() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=[
            TelegramRetryAfter(
                method=_method(),
                message="too many requests",
                retry_after=2,
            ),
            None,
        ]
    )
    bot.send_photo = AsyncMock()
    watcher = _watcher(bot)

    with patch(
        "domonap_bot.telegram.call_watcher.asyncio.sleep",
        new=AsyncMock(),
    ) as sleep:
        await watcher._send_notification([1], "hello")

    assert bot.send_message.await_count == 2
    sleep.assert_awaited_once_with(2.0)


async def test_permanent_telegram_error_is_not_retried() -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=_method(), message="bot was blocked")
    )
    bot.send_photo = AsyncMock()
    watcher = _watcher(bot)

    with patch(
        "domonap_bot.telegram.call_watcher.asyncio.sleep",
        new=AsyncMock(),
    ) as sleep:
        await watcher._send_notification([1], "hello")

    bot.send_message.assert_awaited_once()
    sleep.assert_not_awaited()


async def test_failed_photo_falls_back_to_text_for_same_user() -> None:
    bot = MagicMock()
    bot.send_photo = AsyncMock(
        side_effect=TelegramBadRequest(method=_method(), message="cannot fetch photo")
    )
    bot.send_message = AsyncMock()
    watcher = _watcher(bot)

    await watcher._send_notification(
        [1],
        "hello",
        photo_url="https://example.invalid/photo.jpg",
        door_id="door-1",
        call_id="call-1",
    )

    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == 1
    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    callback_data = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "answer:call-1" in callback_data
    assert "open:door-1" in callback_data
