import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError, NetworkError
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.errors import describe_error
from domonap_bot.telegram.fsm import AdminStates
from domonap_bot.telegram.keyboards import admin_panel_keyboard, back_keyboard, user_list_keyboard

logger = logging.getLogger(__name__)

_pending_removals: dict[int, int] = {}


def register_admin_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    admin_access: AccessControl,
    access: AccessControl | None = None,
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
            message = editable_callback_message(event)
            if message is None:
                await event.answer("Message unavailable", show_alert=True)
                return
            await message.edit_text(text, reply_markup=kb)
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
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        users = await storage.list_allowed_users()
        admin_ids = set(await storage.list_admin_users())
        if not users:
            text = "👥 Users\n─────────────────────\nNo users configured."
        else:
            lines = []
            for uid in users:
                badge = " 👑" if uid in admin_ids else ""
                lines.append(f"👤 {uid}{badge}")
            text = "👥 Users\n─────────────────────\n" + "\n".join(lines)
        await message.edit_text(text, reply_markup=user_list_keyboard(users, admin_ids))
        await callback.answer()

    @router.callback_query(F.data == "a:add")
    @admin_access.require_access
    async def callback_add_user_start(callback: CallbackQuery, state: FSMContext) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        await message.edit_text(
            "Send me the Telegram user ID to add:\n\n"
            "Example: `123456789`\n\n"
            "Type /cancel to abort.",
        )
        await state.set_state(AdminStates.waiting_user_id)
        await callback.answer()

    @router.message(AdminStates.waiting_user_id, F.text == "/cancel")
    async def fsm_cancel_add(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=back_keyboard("a:panel"))

    @router.message(AdminStates.waiting_user_id, F.text)
    @admin_access.require_access
    async def fsm_add_user_id(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("Invalid ID. Please send a numeric Telegram user ID.")
            return

        uid = int(text)
        await storage.set_user_allowed(uid)
        if access is not None:
            access.add_user(uid)
        await message.answer(f"✅ User {uid} added as regular user.")
        await state.clear()

        users = await storage.list_allowed_users()
        admin_ids = set(await storage.list_admin_users())
        text = (
            "👥 Users\n─────────────────────\n"
            + "\n".join(f"👤 {u}{' 👑' if u in admin_ids else ''}" for u in users)
            if users
            else "No users."
        )
        await message.answer(text, reply_markup=user_list_keyboard(users, admin_ids))

    @router.callback_query(F.data == "a:grant")
    @admin_access.require_access
    async def callback_grant_admin_start(callback: CallbackQuery, state: FSMContext) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        await message.edit_text(
            "Send me the Telegram user ID to grant admin rights:\n\n"
            "Example: `123456789`\n\n"
            "Type /cancel to abort.",
        )
        await state.set_state(AdminStates.waiting_grant_admin_id)
        await callback.answer()

    @router.message(AdminStates.waiting_grant_admin_id, F.text == "/cancel")
    async def fsm_cancel_grant_admin(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Cancelled.", reply_markup=back_keyboard("a:panel"))

    @router.message(AdminStates.waiting_grant_admin_id, F.text)
    @admin_access.require_access
    async def fsm_grant_admin_id(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("Invalid ID. Please send a numeric Telegram user ID.")
            return

        uid = int(text)
        if not await storage.is_user_allowed(uid):
            await message.answer(
                f"❌ User {uid} is not registered. Use 'Add user' first.",
            )
            return

        if await storage.is_user_admin(uid):
            await message.answer(f"ℹ️ User {uid} is already an admin.")
            await state.clear()
            return

        await storage.set_user_admin(uid)
        admin_access.add_user(uid)

        await message.answer(f"✅ User {uid} is now an admin.")
        await state.clear()

        users = await storage.list_allowed_users()
        admin_ids = set(await storage.list_admin_users())
        text = (
            "👥 Users\n─────────────────────\n"
            + "\n".join(f"👤 {u}{' 👑' if u in admin_ids else ''}" for u in users)
            if users
            else "No users."
        )
        await message.answer(text, reply_markup=user_list_keyboard(users, admin_ids))

    @router.callback_query(F.data.startswith("a:rm:"))
    @admin_access.require_access
    async def callback_remove_user(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await callback.answer("Invalid user ID.", show_alert=True)
            return
        uid_str = data.removeprefix("a:rm:")
        try:
            uid = int(uid_str)
        except ValueError:
            await callback.answer("Invalid user ID.", show_alert=True)
            return

        admin_id = callback.from_user.id if callback.from_user else 0
        pending = _pending_removals.get(admin_id)

        if pending != uid:
            _pending_removals[admin_id] = uid
            asyncio.get_event_loop().call_later(
                10, lambda: _pending_removals.pop(admin_id, None)
            )
            await callback.answer(f"Tap again to confirm remove user {uid}", show_alert=True)
            return

        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return

        if admin_access.is_allowed(uid) and len(admin_access.user_ids()) <= 1:
            _pending_removals.pop(admin_id, None)
            await callback.answer("Cannot remove the last admin.", show_alert=True)
            return

        _pending_removals.pop(admin_id, None)
        await storage.remove_user(uid)
        if access is not None:
            access.remove_user(uid)
        admin_access.remove_user(uid)
        await callback.answer(f"User {uid} removed.")

        users = await storage.list_allowed_users()
        admin_ids = set(await storage.list_admin_users())
        text = (
            "👥 Users\n─────────────────────\n"
            + "\n".join(f"👤 {u}{' 👑' if u in admin_ids else ''}" for u in users)
            if users
            else "No users."
        )
        await message.edit_text(text, reply_markup=user_list_keyboard(users, admin_ids))

    @router.callback_query(F.data == "a:auth")
    @admin_access.require_access
    async def callback_admin_auth(callback: CallbackQuery) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        phone = client.phone
        if not phone:
            await message.edit_text(
                "No phone configured.", reply_markup=back_keyboard("a:panel")
            )
            await callback.answer()
            return
        await callback.answer("Requesting SMS...")
        try:
            success = await client.login(phone)
        except NetworkError:
            await message.edit_text(
                "Network unavailable. Please try again later.",
                reply_markup=back_keyboard("a:panel"),
            )
            return
        except DomonapError as exc:
            await message.edit_text(
                describe_error(exc),
                reply_markup=back_keyboard("a:panel"),
            )
            return
        if success:
            masked = "".join(c for c in phone if c.isdigit())
            masked = masked[:3] + "***" + masked[-2:] if len(masked) >= 4 else masked
            if phone.startswith("+"):
                masked = f"+{masked}"
            await message.edit_text(
                f"SMS sent to {masked}. Use /code <code> to complete.",
                reply_markup=back_keyboard("a:panel"),
            )
        else:
            await message.edit_text(
                "Failed to request SMS.", reply_markup=back_keyboard("a:panel")
            )

    @router.callback_query(F.data == "a:logout")
    @admin_access.require_access
    async def callback_admin_logout(callback: CallbackQuery) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        await client.token_storage.clear()
        client.mark_session_expired("admin logout")
        await message.edit_text("✅ Logged out.", reply_markup=back_keyboard("a:panel"))
        await callback.answer()
