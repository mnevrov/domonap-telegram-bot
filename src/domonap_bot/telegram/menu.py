import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.invites import InviteManager
from domonap_bot.telegram.ui.renderer import acknowledge_callback, edit_text, send_view
from domonap_bot.telegram.ui.views import View, home_view

logger = logging.getLogger(__name__)

_INVITE_PAYLOAD_PREFIX = "invite_"


def register_menu_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
    invites: InviteManager | None = None,
) -> None:
    del cooldown
    invite_manager = invites if invites is not None else InviteManager(storage)

    def current_home(user_id: int) -> View:
        return home_view(
            authorized=bool(client.access_token or client.refresh_token),
            is_admin=admin_access.is_allowed(user_id),
        )

    async def remember_user(message: Message) -> None:
        if message.from_user is None or message.from_user.id <= 0:
            return
        await storage.set_user_profile(
            message.from_user.id,
            first_name=getattr(message.from_user, "first_name", None),
            username=getattr(message.from_user, "username", None),
        )

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        parts = (message.text or "").split(maxsplit=1)
        payload = parts[1].strip() if len(parts) == 2 else ""

        if payload.startswith(_INVITE_PAYLOAD_PREFIX) and user_id > 0:
            if access.is_allowed(user_id):
                await remember_user(message)
                await send_view(message, current_home(user_id))
                return

            token = payload.removeprefix(_INVITE_PAYLOAD_PREFIX)
            if await invite_manager.consume(token):
                await storage.set_user_allowed(user_id)
                access.add_user(user_id)
                await remember_user(message)
                home = current_home(user_id)
                await send_view(
                    message,
                    View(
                        text=f"✅ Доступ активирован.\n\n{home.text}",
                        keyboard=home.keyboard,
                    ),
                )
                return

            await message.answer(
                "Приглашение недействительно или уже истекло. "
                "Попросите администратора создать новое."
            )
            return

        if not access.is_allowed(user_id):
            await message.answer(
                "Доступ к боту не разрешён.\n\n"
                "Это приватный бот: доступ выдаётся по приглашению администратора."
            )
            return

        await remember_user(message)
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
