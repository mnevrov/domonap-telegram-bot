import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import back_keyboard, call_detail_keyboard, call_list_keyboard

logger = logging.getLogger(__name__)

_PER_PAGE = 10
# Per-user filter state: True = missed only, False = all
user_call_filter: dict[int, bool] = {}


def register_call_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    cooldown: CooldownManager,
) -> None:
    @router.callback_query(F.data.startswith("c:p:"))
    @access.require_access
    async def callback_call_list(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await callback.answer("Invalid data", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return

        page_str = data.removeprefix("c:p:")
        try:
            page = max(0, int(page_str))
        except ValueError:
            page = 0

        uid = callback.from_user.id if callback.from_user else 0
        filter_missed = user_call_filter.get(uid, False)

        try:
            page_data = await client.get_call_logs_page(
                per_page=_PER_PAGE,
                current_page=page + 1,
                missed_calls=filter_missed,
            )
            total_pages = page_data.total_pages
            if page >= total_pages:
                page = total_pages - 1
                page_data = await client.get_call_logs_page(
                    per_page=_PER_PAGE,
                    current_page=page + 1,
                    missed_calls=filter_missed,
                )
        except DomonapError:
            await message.edit_text(
                "Failed to load call logs.", reply_markup=back_keyboard("m:main")
            )
            await callback.answer()
            return

        entries = page_data.entries
        total_pages = page_data.total_pages

        door_map: dict[str, str] = {}
        try:
            doors = await client.get_doors()
            door_map = {d.door_id: d.name for d in doors}
            door_map.update({d.id: d.name for d in doors})
        except Exception:
            pass

        text = "📞 Calls\n─────────────────────\n"
        text += f"Filter: {'Missed' if filter_missed else 'All'}\n\n"

        if not entries:
            text += "No calls found."
        else:
            for entry in entries:
                status = "❌" if not entry.answered else "✅"
                name = door_map.get(
                    entry.door_id or "", entry.caller or entry.call_id[:8]
                )
                time_str = entry.call_time.strftime("%H:%M") if entry.call_time else "??"
                text += f"\n{status} {name} — {time_str}"

        kb = call_list_keyboard(entries, page, total_pages, filter_missed)
        await message.edit_text(text, reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("c:f:"))
    @access.require_access
    async def callback_call_filter(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await callback.answer("Invalid data", show_alert=True)
            return
        uid = callback.from_user.id if callback.from_user else 0
        mode = data.removeprefix("c:f:")
        user_call_filter[uid] = mode == "missed"

        # Re-render list on page 0.
        callback.data = "c:p:0"
        await callback_call_list(callback)

    @router.callback_query(F.data.startswith("c:det:"))
    @access.require_access
    async def callback_call_detail(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await callback.answer("Invalid data", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Message unavailable", show_alert=True)
            return
        call_id = data.removeprefix("c:det:")

        try:
            entry = await client.find_call_log(call_id)
        except DomonapError:
            await message.edit_text(
                "Failed to load call details.", reply_markup=back_keyboard("c:p:0")
            )
            await callback.answer()
            return

        if not entry:
            await message.edit_text("Call not found.", reply_markup=back_keyboard("c:p:0"))
            await callback.answer()
            return

        door_info_map: dict[str, tuple[str, str | None]] = {}
        try:
            doors = await client.get_doors()
            for door in doors:
                url = door.http_video_url or door.webrtc_video_url
                door_info_map[door.door_id] = (door.name, url)
                door_info_map[door.id] = (door.name, url)
        except Exception:
            pass

        door_name, video_url = door_info_map.get(
            entry.door_id or "", (entry.caller or "", None)
        )

        parts = [
            "📞 Call Details",
            "─────────────────────",
            f"Door: {door_name}",
            f"Time: {entry.call_time.strftime('%H:%M:%S') if entry.call_time else '??'}",
            f"Status: {'Answered ✅' if entry.answered else 'Missed ❌'}",
        ]
        text = "\n".join(parts)

        kb = call_detail_keyboard(entry.call_id, entry.door_id, video_url)

        if entry.photo_url:
            try:
                await message.delete()
                await message.answer_photo(
                    photo=entry.photo_url,
                    caption=text,
                    reply_markup=kb,
                )
            except Exception:
                await message.edit_text(text, reply_markup=kb)
        else:
            await message.edit_text(text, reply_markup=kb)
        await callback.answer()
