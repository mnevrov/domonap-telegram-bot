import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import call_list_keyboard, call_detail_keyboard


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

        has_more = len(entries) >= _PER_PAGE

        door_map: dict[str, str] = {}
        try:
            doors = await client.get_doors()
            door_map = {d.door_id: d.name for d in doors}
            door_map.update({d.id: d.name for d in doors})
        except Exception:
            pass

        text = f"📞 Calls\n─────────────────────\n"
        text += f"Filter: {'Missed' if filter_missed else 'All'}\n\n"

        if not entries:
            text += "No calls found."
        else:
            for e in entries:
                status = "❌" if not e.answered else "✅"
                name = door_map.get(e.door_id or "", e.caller or e.call_id[:8])
                time_str = e.call_time.strftime("%H:%M") if e.call_time else "??"
                text += f"\n{status} {name} — {time_str}"

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

        door_info_map: dict[str, tuple[str, str | None]] = {}
        try:
            doors = await client.get_doors()
            for d in doors:
                key = d.door_id or d.id
                url = d.http_video_url or d.webrtc_video_url
                door_info_map[d.door_id] = (d.name, url)
                door_info_map[d.id] = (d.name, url)
        except Exception:
            pass

        door_name, video_url = door_info_map.get(entry.door_id or "", (entry.caller or "", None))

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
