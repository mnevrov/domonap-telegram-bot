from unittest.mock import MagicMock

import pytest

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.bot import build_bot
from tests.test_client import FakeStorage


@pytest.mark.asyncio
async def test_build_bot_wires_router_without_error() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[],
        admin_telegram_user_ids=[],
    )
    client = MagicMock(spec=DomonapClient)

    bot, dp = await build_bot(settings, client)
    try:
        assert bot.token == "123456:TEST-TOKEN"
        assert len(dp.sub_routers) == 1
        router = dp.sub_routers[0]
        assert len(router.message.handlers) > 0
        assert len(router.callback_query.handlers) > 0
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_runtime_allow_list_is_union_of_env_and_persisted_users() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[100],
        admin_telegram_user_ids=[],
    )
    storage = FakeStorage()
    await storage.set_user_allowed(200)
    access = AccessControl(settings.allowed_telegram_user_ids)

    bot, _ = await build_bot(settings, MagicMock(spec=DomonapClient), storage, access)
    try:
        assert access.user_ids() == [100, 200]
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_env_allowed_user_remains_bootstrap_floor_when_not_persisted() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[100],
        admin_telegram_user_ids=[],
    )
    storage = FakeStorage()
    access = AccessControl(settings.allowed_telegram_user_ids)

    bot, _ = await build_bot(settings, MagicMock(spec=DomonapClient), storage, access)
    try:
        assert access.user_ids() == [100]
        assert await storage.is_user_allowed(100) is False
    finally:
        await bot.session.close()
