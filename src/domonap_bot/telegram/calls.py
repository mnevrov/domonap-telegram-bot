import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import call_list_keyboard, call_detail_keyboard
from domonap_bot.telegram.menu import _render

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
        page_str = callback.data.removeprefix("c:p:")
        try:
            page = int(page_str)
        except ValueError:
            page = 0

        uid = callback.from_user.id if callback.from_user else 0
        filter_missed = user_call_filter.get(uid, False)

        try:
            entries = await client.get_call_logs(
                per_page=_PER_PAGE,
                current_page=page + 1,
                missed_calls=filter_missed,
            )
        except DomonapError:
            await callback.message.edit_text("Failed to load call logs.")
            await callback.answer()
            return

        if not entries and page > 0:
            page = 0
            try:
                entries = await client.get_call_logs(
                    per_page=_PER_PAGE,
                    current_page=1,
                    missed_calls=filter_missed,
                )
            except DomonapError:
                await callback.message.edit_text("Failed to load call logs.")
                await callback.answer()
                return

        # Estimate total pages from API (we don't have total count from client directly)
        # Use the PagedResponse — but get_call_logs returns flat list. We'll assume
        # if fewer than per_page, it's the last page.
        has_more = len(entries) >= _PER_PAGE
        # Since we don't have total, use 999 as "more" indicator
        if has_more:
            total_pages_display = f"{page + 1}+"
        else:
            total_pages_display = str(page + 1)

        text = f"📞 Calls\n─────────────────────\n"
        text += f"Filter: {'Missed' if filter_missed else 'All'}\n\n"

        if not entries:
            text += "No calls found."
        else:
            for e in entries:
                status = "❌" if not e.answered else "✅"
                name = ""
                if e.door_id:
                    try:
                        doors = await client.get_doors()
                        door = next(
                            (d for d in doors if d.door_id == e.door_id or d.id == e.door_id), None
                        )
                        if door:
                            name = door.name
                    except Exception:
                        pass
                time_str = e.call_time.strftime("%H:%M") if e.call_time else "??"
                text += f"\n{status} {name or e.caller or e.call_id[:8]} — {time_str}"

        kb = call_list_keyboard(entries, page, max(1, page + (1 if has_more else 0)), filter_missed)
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("c:f:"))
    @access.require_access
    async def callback_call_filter(callback: CallbackQuery) -> None:
        uid = callback.from_user.id if callback.from_user else 0
        mode = callback.data.removeprefix("c:f:")
        user_call_filter[uid] = mode == "missed"

        # Re-render list on page 0
        cb = callback
        cb.data = "c:p:0"
        # Re-dispatch to the list handler
        await callback_call_list(cb)

    @router.callback_query(F.data.startswith("c:det:"))
    @access.require_access
    async def callback_call_detail(callback: CallbackQuery) -> None:
        call_id = callback.data.removeprefix("c:det:")

        try:
            entries = await client.get_call_logs(per_page=50, missed_calls=False)
        except DomonapError:
            await callback.message.edit_text("Failed to load call details.")
            await callback.answer()
            return

        entry = next((e for e in entries if e.call_id == call_id), None)
        if not entry:
            await callback.message.edit_text("Call not found.")
            await callback.answer()
            return

        door_name = entry.caller or ""
        if entry.door_id:
            try:
                doors = await client.get_doors()
                door = next(
                    (d for d in doors if d.door_id == entry.door_id or d.id == entry.door_id), None
                )
                if door:
                    door_name = door.name
            except Exception:
                pass

        parts = [
            "📞 Call Details",
            "─────────────────────",
            f"Door: {door_name}",
            f"Time: {entry.call_time.strftime('%H:%M:%S') if entry.call_time else '??'}",
            f"Status: {'Answered ✅' if entry.answered else 'Missed ❌'}",
        ]
        text = "\n".join(parts)

        video_url = None
        if entry.door_id:
            try:
                doors = await client.get_doors()
                door = next(
                    (d for d in doors if d.door_id == entry.door_id or d.id == entry.door_id), None
                )
                if door:
                    video_url = door.http_video_url or door.webrtc_video_url
            except Exception:
                pass

        kb = call_detail_keyboard(entry.call_id, entry.door_id, video_url)

        if entry.photo_url:
            try:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=entry.photo_url,
                    caption=text,
                    reply_markup=kb,
                )
            except Exception:
                await callback.message.edit_text(text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
