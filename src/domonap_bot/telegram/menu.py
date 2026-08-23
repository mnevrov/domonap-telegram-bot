import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.ui.renderer import acknowledge_callback, edit_text, send_view
from domonap_bot.telegram.ui.views import home_view

logger = logging.getLogger(__name__)


def register_menu_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    del storage, cooldown

    def current_home(user_id: int):
        return home_view(
            authorized=bool(client.access_token or client.refresh_token),
            is_admin=admin_access.is_allowed(user_id),
        )

    @router.message(Command("start"))
    @access.require_access
    async def cmd_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        await send_view(message, current_home(user_id))

    @router.callback_query(F.data == "m:main")
    @access.require_access
    async def callback_main_menu(callback: CallbackQuery) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await acknowledge_callback(
                callback,
                "Сообщение недоступно",
                show_alert=True,
            )
            return

        await acknowledge_callback(callback)
        user_id = callback.from_user.id if callback.from_user else 0
        await edit_text(message, current_home(user_id))

    @router.callback_query(F.data == "noop")
    async def callback_noop(callback: CallbackQuery) -> None:
        await acknowledge_callback(callback)
