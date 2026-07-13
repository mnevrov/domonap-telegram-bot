import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.fsm import AdminStates
from domonap_bot.telegram.keyboards import admin_panel_keyboard, user_list_keyboard, back_keyboard

logger = logging.getLogger(__name__)


def register_admin_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    admin_access: AccessControl,
) -> None:
    async def _admin_panel(event: Message | CallbackQuery) -> None:
        has_token = client.access_token or client.refresh_token
        users = await storage.list_allowed_users()
        parts = [
            "⚙️ Admin Panel",
            "─────────────────────",
            f"Auth: {'✅' if has_token else '❌'}",
            f"Users: {len(users)}",
            "",
        ]
        text = "\n".join(parts)
        kb = admin_panel_keyboard()
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, reply_markup=kb)
            await event.answer()
        else:
            await event.answer(text, reply_markup=kb)

    @router.callback_query(F.data == "a:panel")
    @admin_access.require_access
    async def callback_admin_panel(callback: CallbackQuery) -> None:
        await _admin_panel(callback)

    @router.callback_query(F.data == "a:users")
    @admin_access.require_access
    async def callback_user_list(callback: CallbackQuery) -> None:
        users = await storage.list_allowed_users()
        if not users:
            text = "👥 Users\n─────────────────────\nNo users configured."
        else:
            text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {uid}" for uid in users)
        await callback.message.edit_text(text, reply_markup=user_list_keyboard(users))
        await callback.answer()

    @router.callback_query(F.data == "a:add")
    @admin_access.require_access
    async def callback_add_user_start(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.message.edit_text(
            "Send me the Telegram user ID to add:\n\n"
            "Example: `123456789`\n\n"
            "Type /cancel to abort.",
        )
        await state.set_state(AdminStates.waiting_user_id)
        await callback.answer()

    @router.message(AdminStates.waiting_user_id, F.text)
    @admin_access.require_access
    async def fsm_add_user_id(message: Message, state: FSMContext) -> None:
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("Invalid ID. Please send a numeric Telegram user ID.")
            return

        uid = int(text)
        await storage.set_user_allowed(uid)
        await message.answer(f"✅ User {uid} added.")
        await state.clear()

        users = await storage.list_allowed_users()
        text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {u}" for u in users) if users else "No users."
        await message.answer(text, reply_markup=user_list_keyboard(users))

    @router.message(AdminStates.waiting_user_id, F.text == "/cancel")
    async def fsm_cancel_add(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=back_keyboard("a:panel"))

    @router.callback_query(F.data.startswith("a:rm:"))
    @admin_access.require_access
    async def callback_remove_user(callback: CallbackQuery) -> None:
        uid_str = callback.data.removeprefix("a:rm:")
        try:
            uid = int(uid_str)
        except ValueError:
            await callback.answer("Invalid user ID.", show_alert=True)
            return

        await storage.remove_user(uid)
        await callback.answer(f"User {uid} removed.")

        users = await storage.list_allowed_users()
        text = "👥 Users\n─────────────────────\n" + "\n".join(f"👤 {u}" for u in users) if users else "No users."
        await callback.message.edit_text(text, reply_markup=user_list_keyboard(users))

    @router.callback_query(F.data == "a:auth")
    @admin_access.require_access
    async def callback_admin_auth(callback: CallbackQuery) -> None:
        phone = client.phone
        if not phone:
            await callback.message.edit_text("No phone configured.", reply_markup=back_keyboard("a:panel"))
            await callback.answer()
            return
        success = await client.login(phone)
        if success:
            masked = "".join(c for c in phone if c.isdigit())
            masked = masked[:3] + "***" + masked[-2:] if len(masked) >= 4 else masked
            if phone.startswith("+"):
                masked = f"+{masked}"
            await callback.message.edit_text(
                f"SMS sent to {masked}. Use /code <code> to complete.",
                reply_markup=back_keyboard("a:panel"),
            )
        else:
            await callback.message.edit_text("Failed to request SMS.", reply_markup=back_keyboard("a:panel"))
        await callback.answer()

    @router.callback_query(F.data == "a:logout")
    @admin_access.require_access
    async def callback_admin_logout(callback: CallbackQuery) -> None:
        await client.token_storage.clear()
        client.mark_session_expired("admin logout")
        await callback.message.edit_text("✅ Logged out.", reply_markup=back_keyboard("a:panel"))
        await callback.answer()
