from unittest.mock import MagicMock

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.telegram.bot import build_bot


def test_build_bot_wires_router_without_error() -> None:
    settings = Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[],
        admin_telegram_user_ids=[],
    )
    client = MagicMock(spec=DomonapClient)

    bot, dp = build_bot(settings, client)

    assert bot.token == "123456:TEST-TOKEN"
    assert len(dp.sub_routers) == 1
    router = dp.sub_routers[0]
    assert len(router.message.handlers) > 0
    assert len(router.callback_query.handlers) > 0
