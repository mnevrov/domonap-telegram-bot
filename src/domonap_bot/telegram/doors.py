import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message, resolve_callback_id
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.errors import describe_error
from domonap_bot.telegram.keyboards import CameraUrlProvider, back_keyboard, retry_back_keyboard
from domonap_bot.telegram.navigation import NavigationStore
from domonap_bot.telegram.ui.renderer import acknowledge_callback, edit_text
from domonap_bot.telegram.ui.views import View, door_detail_view, door_list_view

logger = logging.getLogger(__name__)

_PER_PAGE = 10


def register_door_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    cooldown: CooldownManager,
    navigation: NavigationStore | None = None,
    camera_url_provider: CameraUrlProvider | None = None,
) -> None:
    nav = navigation if navigation is not None else NavigationStore()

    async def _render_door_list(callback: CallbackQuery, page: int) -> None:
        message = editable_callback_message(callback)
        if message is None:
            return
        uid = callback.from_user.id if callback.from_user else 0

        try:
            doors = await client.get_doors()
        except DomonapError:
            await edit_text(
                message,
                View(
                    "Не удалось загрузить двери.",
                    retry_back_keyboard(f"d:p:{page}"),
                ),
            )
            return

        total = len(doors)
        total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
        page = min(max(0, page), total_pages - 1)
        nav.set_door_page(uid, page)
        start = page * _PER_PAGE
        page_doors = doors[start : start + _PER_PAGE]
        await edit_text(
            message,
            door_list_view(
                page_doors,
                page=page,
                total_pages=total_pages,
                total=total,
                camera_url_provider=camera_url_provider,
            ),
        )

    @router.callback_query(F.data.startswith("d:p:"))
    @access.require_access
    async def callback_door_list(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        if editable_callback_message(callback) is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return

        page_str = data.removeprefix("d:p:")
        try:
            page = max(0, int(page_str))
        except ValueError:
            page = 0

        await acknowledge_callback(callback)
        await _render_door_list(callback, page)

    @router.callback_query(F.data == "d:back")
    @access.require_access
    async def callback_door_back(callback: CallbackQuery) -> None:
        if editable_callback_message(callback) is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return
        uid = callback.from_user.id if callback.from_user else 0
        page = nav.get(uid).door_page
        await acknowledge_callback(callback)
        await _render_door_list(callback, page)

    @router.callback_query(F.data.startswith("d:det:"))
    @access.require_access
    async def callback_door_detail(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return
        door_id = resolve_callback_id(data.removeprefix("d:det:"))

        await acknowledge_callback(callback)
        try:
            doors = await client.get_doors()
        except DomonapError:
            await edit_text(
                message,
                View(
                    "Не удалось загрузить данные двери.",
                    back_keyboard("d:back", "← Двери"),
                ),
            )
            return

        door = next((item for item in doors if item.door_id == door_id), None)
        if door is None:
            await edit_text(
                message,
                View("Дверь не найдена.", back_keyboard("d:back", "← Двери")),
            )
            return

        await edit_text(message, door_detail_view(door, camera_url_provider=camera_url_provider))

    @router.callback_query(F.data.startswith("d:open:"))
    @access.require_access
    async def callback_door_open(callback: CallbackQuery) -> None:
        data = callback.data
        if not data:
            await acknowledge_callback(callback, "Некорректные данные", show_alert=True)
            return
        message = editable_callback_message(callback)
        if message is None:
            await acknowledge_callback(callback, "Сообщение недоступно", show_alert=True)
            return
        door_id = resolve_callback_id(data.removeprefix("d:open:"))
        user_id = callback.from_user.id if callback.from_user else 0

        if not cooldown.is_ready(user_id, door_id):
            remaining = cooldown.remaining(user_id, door_id)
            await acknowledge_callback(
                callback,
                f"Повторите через {remaining:.0f} с",
                show_alert=True,
            )
            return

        await acknowledge_callback(callback, "Открываю…")
        cooldown.set(user_id, door_id)

        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            cooldown.clear(user_id, door_id)
            await edit_text(
                message,
                View(
                    f"❌ {describe_error(exc)}",
                    back_keyboard("d:back", "← Двери"),
                ),
            )
            return

        if not success:
            cooldown.clear(user_id, door_id)

        if success:
            view = View(
                "✅ Дверь открыта.",
                back_keyboard("d:back", "← Двери"),
            )
        else:
            view = View(
                "❌ Не удалось открыть дверь.",
                back_keyboard("d:back", "← К дверям"),
            )
        await edit_text(message, view)
