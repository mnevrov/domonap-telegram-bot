import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

# Per-user tracked dashboard message_id
dashboard: dict[int, int] = {}


async def _render(
    target: Message | CallbackQuery,
    text: str,
    kb,
) -> None:
    if isinstance(target, CallbackQuery) and target.message:
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    elif isinstance(target, Message):
        sent = await target.answer(text, reply_markup=kb)
        if sent and hasattr(sent, "message_id"):
            uid = target.from_user.id if target.from_user else 0
            dashboard[uid] = sent.message_id


def register_menu_handlers(
    router: Router,
    client: DomonapClient,
    storage: SqliteStorage,
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
