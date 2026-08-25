from unittest.mock import AsyncMock, MagicMock

import pytest

from domonap_bot.config import Settings
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.call_watcher import CallWatcher
from domonap_bot.telegram.keyboards import (
    call_detail_keyboard,
    door_detail_keyboard,
    door_list_keyboard,
)
from domonap_bot.telegram.url_policy import safe_http_url


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example.com/image.jpg",
        "http://video.example.com/live/stream.m3u8?token=abc#fragment",
    ],
)
def test_safe_http_url_accepts_http_and_https(url: str) -> None:
    assert safe_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/plain,secret",
        "file:///etc/passwd",
        "https://user:password@example.com/video",
        "https://example.com/video\nInjected: header",
        "https://",
        "x" * 2049,
    ],
)
def test_safe_http_url_rejects_unsafe_values(url: str) -> None:
    assert safe_http_url(url) is None


def test_door_keyboard_omits_unsafe_video_url() -> None:
    door = DoorKey(
        id="key-1",
        doorId="door-1",
        name="Door",
        httpVideoUrl="javascript:alert(1)",
    )

    keyboard = door_detail_keyboard(door)

    assert all(button.url is None for row in keyboard.inline_keyboard for button in row)


def test_door_keyboard_validates_camera_provider_url() -> None:
    door = DoorKey(id="key-1", doorId="door-1", name="Door")

    keyboard = door_list_keyboard(
        [door],
        page=0,
        total_pages=1,
        camera_url_provider=lambda _: "javascript:alert(1)",
    )

    assert all(button.url is None for row in keyboard.inline_keyboard for button in row)


def test_call_keyboard_omits_embedded_credentials() -> None:
    keyboard = call_detail_keyboard(
        "call-1",
        "door-1",
        "https://user:password@example.com/video",
    )

    assert all(button.url is None for row in keyboard.inline_keyboard for button in row)


async def test_watcher_unsafe_photo_falls_back_to_text() -> None:
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_message = AsyncMock()
    watcher = CallWatcher(
        MagicMock(),
        bot,
        Settings(telegram_bot_token="123456:TEST-TOKEN", allowed_telegram_user_ids=[1]),
    )

    await watcher._send_notification(
        user_ids=[1],
        text="Incoming call",
        photo_url="file:///etc/passwd",
    )

    bot.send_photo.assert_not_awaited()
    bot.send_message.assert_awaited_once()
