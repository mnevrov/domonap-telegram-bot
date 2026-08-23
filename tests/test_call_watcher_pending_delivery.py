from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from domonap_bot.config import Settings
from domonap_bot.domonap.models import CallLogEntry
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.call_watcher import (
    _NOTIFICATION_MAX_DELIVERY_ROUNDS,
    CallWatcher,
)


def _make_watcher(*, access: AccessControl | None = None) -> CallWatcher:
    settings = Settings(
        telegram_bot_token="test:token",
        allowed_telegram_user_ids=[101, 202],
        admin_telegram_user_ids=[],
        call_watcher_enabled=True,
    )
    client = MagicMock()
    client.get_doors = AsyncMock(return_value=[])
    client.get_call_logs = AsyncMock(return_value=[])
    client.refresh_session = AsyncMock(return_value=True)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    return CallWatcher(client, bot, settings, access=access)


@pytest.mark.asyncio
async def test_retry_round_targets_only_previous_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    watcher = _make_watcher()
    attempted_users: list[int] = []
    outcomes = {101: True, 202: False}

    async def fake_send_with_retry(
        _send: Callable[[], Awaitable[Any]], *, user_id: int, kind: str
    ) -> bool:
        del kind
        attempted_users.append(user_id)
        return outcomes[user_id]

    monkeypatch.setattr(watcher, "_send_with_retry", fake_send_with_retry)
    entry = CallLogEntry(call_id="call-1", answered=False)

    await watcher._handle_entry(entry)

    assert attempted_users == [101, 202]
    assert watcher.get_seen_ids_count() == 0
    assert watcher.get_pending_delivery_count() == 1

    attempted_users.clear()
    outcomes[202] = True
    await watcher._handle_entry(entry)

    assert attempted_users == [202]
    assert watcher.get_seen_ids_count() == 1
    assert watcher.get_pending_delivery_count() == 0

    attempted_users.clear()
    await watcher._handle_entry(entry)
    assert attempted_users == []


@pytest.mark.asyncio
async def test_delivery_rounds_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    watcher = _make_watcher(access=AccessControl([101]))
    attempted_users: list[int] = []

    async def always_fail(
        _send: Callable[[], Awaitable[Any]], *, user_id: int, kind: str
    ) -> bool:
        del kind
        attempted_users.append(user_id)
        return False

    monkeypatch.setattr(watcher, "_send_with_retry", always_fail)
    entry = CallLogEntry(call_id="call-fail", answered=False)

    for _ in range(_NOTIFICATION_MAX_DELIVERY_ROUNDS):
        await watcher._handle_entry(entry)

    assert attempted_users == [101] * _NOTIFICATION_MAX_DELIVERY_ROUNDS
    assert watcher.get_pending_delivery_count() == 0
    assert watcher.get_seen_ids_count() == 1

    await watcher._handle_entry(entry)
    assert attempted_users == [101] * _NOTIFICATION_MAX_DELIVERY_ROUNDS


@pytest.mark.asyncio
async def test_revoked_pending_recipient_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    access = AccessControl([101, 202])
    watcher = _make_watcher(access=access)
    attempted_users: list[int] = []

    async def first_round(
        _send: Callable[[], Awaitable[Any]], *, user_id: int, kind: str
    ) -> bool:
        del kind
        attempted_users.append(user_id)
        return user_id == 101

    monkeypatch.setattr(watcher, "_send_with_retry", first_round)
    entry = CallLogEntry(call_id="call-revoke", answered=False)

    await watcher._handle_entry(entry)
    assert attempted_users == [101, 202]
    assert watcher.get_pending_delivery_count() == 1

    attempted_users.clear()
    access.remove_user(202)
    await watcher._handle_entry(entry)

    assert attempted_users == []
    assert watcher.get_pending_delivery_count() == 0
    assert watcher.get_seen_ids_count() == 1
