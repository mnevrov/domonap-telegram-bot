from aiogram import Bot, Dispatcher, Router

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.handlers import register_handlers


def build_bot(
    settings: Settings,
    client: DomonapClient,
) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    router = Router()

    access = AccessControl(settings.allowed_telegram_user_ids)
    register_handlers(router, client, access)

    dp.include_router(router)
    return bot, dp
