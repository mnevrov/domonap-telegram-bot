import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.keyboards import back_keyboard
from domonap_bot.telegram.ui.renderer import acknowledge_callback, edit_text
from domonap_bot.telegram.ui.views import View, call_detail_view, calls_view
from domonap_bot.telegram.url_policy import safe_http_url

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
    del cooldown

    async def _render_call_list(callback: CallbackQuery, page: int) -> None:
        message = editable_callback_message(callback)
        if message is None:
            return

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
            await edit_text(
                message,
                View("Не удалось загрузить журнал звонков.", back_keyboard("m:main", "← Главное меню")),
            )
            return

        door_map: dict[str, str] = {}
        try:
            doors = await client.get_doors()
            door_map = {door.door_id: door.name for door in doors}
            door_map.update({door.id: door.name for door in doors})
        except DomonapError:
            pass

        names_by_call_id = {
            entry.call_id: door_map.get(
                entry.door_id or "",
                entry.caller or entry.call_id[:8],
            )
            for entry in page_data.entries
        }
        await edit_text(
            message,
            calls_view(
                page_data.entries,
                page=page,
                total_pages=page_data.total_pages,
                filter_missed=filter_missed,
                names_by_call_id=names_by_call_id,
            ),
        )

    @router.callback_query(F.data.startswith("c:p:"))
    @access.require_access
    async def callback_call_list(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return

        page_str = data.removeprefix("c:p:")
        try:
            page = max(0, int(page_str))
        except ValueError:
            page = 0

        await acknowledge_callback(callback)
        await _render_call_list(callback, page)

    @router.callback_query(F.data.startswith("c:f:"))
    @access.require_access
    async def callback_call_filter(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        if editable_callback_message(callback) is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return

        uid = callback.from_user.id if callback.from_user else 0
        mode = data.removeprefix("c:f:")
        user_call_filter[uid] = mode == "missed"

        await acknowledge_callback(callback)
        await _render_call_list(callback, 0)

    @router.callback_query(F.data.startswith("c:det:"))
    @access.require_access
    async def callback_call_detail(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return
        call_id = data.removeprefix("c:det:")

        await acknowledge_callback(callback)
        try:
            entry = await client.find_call_log(call_id)
        except DomonapError:
            await edit_text(
                message,
                View("Не удалось загрузить звонок.", back_keyboard("c:p:0", "← Звонки")),
            )
            return

        if entry is None:
            await edit_text(message, View("Звонок не найден.", back_keyboard("c:p:0", "← Звонки")))
            return

        door_info_map: dict[str, tuple[str, str | None]] = {}
        try:
            doors = await client.get_doors()
            for door in doors:
                url = safe_http_url(door.http_video_url) or safe_http_url(door.webrtc_video_url)
                door_info_map[door.door_id] = (door.name, url)
                door_info_map[door.id] = (door.name, url)
        except DomonapError:
            pass

        door_name, video_url = door_info_map.get(
            entry.door_id or "",
            (entry.caller or "", None),
        )
        view = call_detail_view(entry, door_name=door_name, video_url=video_url)
        photo_url = safe_http_url(entry.photo_url)

        if photo_url:
            try:
                await message.answer_photo(
                    photo=photo_url,
                    caption=view.text,
                    reply_markup=view.keyboard,
                )
            except Exception as exc:
                logger.warning("Failed to send call detail photo: %s", exc)
                await edit_text(message, view)
            else:
                try:
                    await message.delete()
                except Exception as exc:
                    logger.debug("Failed to delete previous call detail message: %s", exc)
        else:
            await edit_text(message, view)
