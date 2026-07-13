import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import door_list_keyboard, door_detail_keyboard
from domonap_bot.telegram.menu import _render

logger = logging.getLogger(__name__)

_PER_PAGE = 10


def register_door_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.callback_query(F.data.startswith("d:p:"))
    @access.require_access
    async def callback_door_list(callback: CallbackQuery) -> None:
        page_str = callback.data.removeprefix("d:p:")
        try:
            page = int(page_str)
        except ValueError:
            page = 0

        try:
            doors = await client.get_doors()
        except DomonapError:
            await callback.message.edit_text("Failed to load doors.")
            await callback.answer()
            return

        total = len(doors)
        total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
        start = page * _PER_PAGE
        page_doors = doors[start: start + _PER_PAGE]

        text = f"🚪 Doors ({total})\n─────────────────────\n" if total > 0 else "No doors available."
        lines = [f"{start + i + 1}. 🚪 {d.name}" for i, d in enumerate(page_doors)]
        text += "\n".join(lines)

        kb = door_list_keyboard(page_doors, page, total_pages)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("d:det:"))
    @access.require_access
    async def callback_door_detail(callback: CallbackQuery) -> None:
        door_id = callback.data.removeprefix("d:det:")

        try:
            doors = await client.get_doors()
        except DomonapError:
            await callback.message.edit_text("Failed to load door details.")
            await callback.answer()
            return

        door = next((d for d in doors if d.id == door_id), None)
        if not door:
            await callback.message.edit_text("Door not found.")
            await callback.answer()
            return

        parts = [
            f"🚪 {door.name}",
            "─────────────────────",
        ]
        if door.domofon_public_pin:
            masked = door.domofon_public_pin[:2] + "****" + door.domofon_public_pin[-2:] if len(door.domofon_public_pin) >= 4 else "****"
            parts.append(f"PIN: {masked}")
        if door.http_video_url or door.webrtc_video_url:
            parts.append("📹 Video available")
        text = "\n".join(parts)

        await callback.message.edit_text(text, reply_markup=door_detail_keyboard(door))
        await callback.answer()

    @router.callback_query(F.data.startswith("d:open:"))
    @access.require_access
    async def callback_door_open(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Invalid data", show_alert=True)
            return
        door_id = callback.data.removeprefix("d:open:")
        user_id = callback.from_user.id if callback.from_user else 0

        if not cooldown.is_ready(user_id, door_id):
            remaining = cooldown.remaining(user_id, door_id)
            await callback.answer(f"Wait {remaining:.0f}s", show_alert=True)
            return

        await callback.answer("Opening...")
        cooldown.set(user_id, door_id)

        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            await callback.message.edit_text(f"❌ {exc}")
            return

        text = "✅ Door opened!" if success else "❌ Failed to open."
        await callback.message.edit_text(
            text,
            reply_markup=door_detail_keyboard(
                DoorKey(id=door_id, door_id=door_id, name="")
            ),
        )
