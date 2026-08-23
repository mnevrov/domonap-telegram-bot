from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.aiohttp import AiohttpSession

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.admin import register_admin_handlers
from domonap_bot.telegram.calls import register_call_handlers
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.doors import register_door_handlers
from domonap_bot.telegram.handlers import register_handlers
from domonap_bot.telegram.menu import register_menu_handlers
from domonap_bot.telegram.navigation import NavigationStore


async def build_bot(
    settings: Settings,
    client: DomonapClient,
    storage: Storage | None = None,
    access: AccessControl | None = None,
) -> tuple[Bot, Dispatcher]:
    session = AiohttpSession()
    session.timeout = 120
    bot = Bot(token=settings.telegram_bot_token, session=session)
    dp = Dispatcher()
    router = Router()

    runtime_access = access or AccessControl(settings.allowed_telegram_user_ids)
    admin_access = AccessControl([], default_allow=False)

    if storage is not None:
        stored_users = await storage.list_allowed_users()
        for uid in stored_users:
            runtime_access.add_user(uid)
            if await storage.is_user_admin(uid):
                admin_access.add_user(uid)

    for uid in settings.admin_telegram_user_ids:
        if runtime_access.is_allowed(uid):
            admin_access.add_user(uid)

    cooldown = CooldownManager()
    navigation = NavigationStore()
    register_handlers(router, client, runtime_access, admin_access, cooldown)

    if storage is not None:
        register_menu_handlers(router, client, storage, runtime_access, admin_access, cooldown)
        register_admin_handlers(router, client, storage, admin_access, runtime_access)

    register_door_handlers(router, client, runtime_access, cooldown, navigation)
    register_call_handlers(router, client, runtime_access, cooldown, navigation)

    dp.include_router(router)
    return bot, dp
