import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def _render(
    target: Message | CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    if isinstance(target, CallbackQuery):
        message = editable_callback_message(target)
        if message is None:
            await target.answer("Message unavailable", show_alert=True)
            return
        await message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


def register_menu_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.message(Command("start"))
    @access.require_access
    async def cmd_start(message: Message) -> None:
        has_token = client.access_token or client.refresh_token
        doors_count = 0
        try:
            doors = await client.get_doors()
            doors_count = len(doors)
        except Exception:
            pass

        parts = [
            "🏠 Domonap Bot",
            "─────────────────────",
            f"Status: {'✅ Authorized' if has_token else '❌ Not authorized'}",
            f"Doors: {doors_count}",
            "",
        ]
        text = "\n".join(parts)
        is_admin = admin_access.is_allowed(message.from_user.id if message.from_user else 0)
        await _render(message, text, main_menu_keyboard(is_admin))

    @router.callback_query(F.data == "m:main")
    @access.require_access
    async def callback_main_menu(callback: CallbackQuery) -> None:
        has_token = client.access_token or client.refresh_token
        doors_count = 0
        try:
            doors = await client.get_doors()
            doors_count = len(doors)
        except Exception:
            pass

        parts = [
            "🏠 Domonap Bot",
            "─────────────────────",
            f"Status: {'✅ Authorized' if has_token else '❌ Not authorized'}",
            f"Doors: {doors_count}",
            "",
        ]
        text = "\n".join(parts)
        is_admin = admin_access.is_allowed(callback.from_user.id if callback.from_user else 0)
        await _render(callback, text, main_menu_keyboard(is_admin))

    @router.callback_query(F.data == "noop")
    async def callback_noop(callback: CallbackQuery) -> None:
        await callback.answer()
