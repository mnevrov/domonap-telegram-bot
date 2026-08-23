import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError, NetworkError
from domonap_bot.storage.base import Storage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.callback_utils import editable_callback_message
from domonap_bot.telegram.errors import describe_error
from domonap_bot.telegram.invites import InviteManager
from domonap_bot.telegram.keyboards import (
    admin_panel_keyboard,
    back_keyboard,
    confirm_remove_user_keyboard,
    confirm_revoke_admin_keyboard,
    user_detail_keyboard,
    user_list_keyboard,
)

logger = logging.getLogger(__name__)


def _parse_telegram_user_id(value: str) -> int | None:
    text = value.strip()
    if not text.isascii() or not text.isdecimal():
        return None
    user_id = int(text)
    return user_id if user_id > 0 else None


def register_admin_handlers(
    router: Router,
    client: DomonapClient,
    storage: Storage,
    admin_access: AccessControl,
    access: AccessControl | None = None,
    invites: InviteManager | None = None,
) -> None:
    role_lock = asyncio.Lock()
    invite_manager = invites if invites is not None else InviteManager(storage)

    async def _render_user_list(message: Message) -> None:
        users = sorted(await storage.list_allowed_users())
        admin_ids = set(await storage.list_admin_users())
        text = "👥 Пользователи"
        if users:
            text += f"\n\nВсего: {len(users)}\nВыберите пользователя:"
        else:
            text += "\n\nПользователей пока нет."
        await message.edit_text(text, reply_markup=user_list_keyboard(users, admin_ids))

    async def _render_user_detail(message: Message, user_id: int) -> bool:
        if not await storage.is_user_allowed(user_id):
            await message.edit_text(
                "Пользователь больше не имеет доступа.",
                reply_markup=back_keyboard("a:users", "← Пользователи"),
            )
            return False
        is_admin = await storage.is_user_admin(user_id)
        role = "Администратор 👑" if is_admin else "Пользователь"
        await message.edit_text(
            f"👤 Пользователь\n\nID: {user_id}\nРоль: {role}\nДоступ: ✅",
            reply_markup=user_detail_keyboard(user_id, is_admin=is_admin),
        )
        return True

    async def _admin_panel(event: Message | CallbackQuery) -> None:
        has_token = bool(client.access_token or client.refresh_token)
        users = await storage.list_allowed_users()
        text = (
            "⚙️ Управление\n\n"
            f"Domonap: {'✅ подключён' if has_token else '⚠️ не подключён'}\n"
            f"Пользователей: {len(users)}"
        )
        kb = admin_panel_keyboard()
        if isinstance(event, CallbackQuery):
            message = editable_callback_message(event)
            if message is None:
                await event.answer("Сообщение недоступно", show_alert=True)
                return
            await event.answer()
            await message.edit_text(text, reply_markup=kb)
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
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        await callback.answer()
        await _render_user_list(message)

    @router.callback_query(F.data == "a:invite")
    @admin_access.require_access
    async def callback_create_invite(callback: CallbackQuery, bot: Bot) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        admin_id = callback.from_user.id if callback.from_user else 0
        if admin_id <= 0:
            await callback.answer("Не удалось определить администратора", show_alert=True)
            return

        await callback.answer("Создаю приглашение…")
        try:
            bot_user = await bot.get_me()
        except Exception as exc:
            logger.warning("Failed to resolve bot username for invite: %s", exc)
            await message.edit_text(
                "Не удалось создать ссылку приглашения.",
                reply_markup=back_keyboard("a:users", "← Пользователи"),
            )
            return
        if not bot_user.username:
            await message.edit_text(
                "У бота не настроено имя пользователя — deep-link недоступен.",
                reply_markup=back_keyboard("a:users", "← Пользователи"),
            )
            return

        invite = await invite_manager.create(created_by=admin_id)
        url = f"https://t.me/{bot_user.username}?start=invite_{invite.token}"
        await message.edit_text(
            "🔗 Приглашение создано\n\n"
            "Отправьте ссылку нужному человеку:\n"
            f"{url}\n\n"
            "Ссылка одноразовая и действует 15 минут.",
            reply_markup=back_keyboard("a:users", "← Пользователи"),
        )

    @router.callback_query(F.data.startswith("a:user:"))
    @admin_access.require_access
    async def callback_user_detail(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:user:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return
        await callback.answer()
        await _render_user_detail(message, user_id)

    @router.callback_query(F.data.startswith("a:grant:"))
    @admin_access.require_access
    async def callback_grant_admin(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:grant:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return

        async with role_lock:
            if not await storage.is_user_allowed(user_id):
                await callback.answer("У пользователя больше нет доступа", show_alert=True)
                return
            if not await storage.is_user_admin(user_id):
                await storage.set_user_admin(user_id)
                admin_access.add_user(user_id)

        await callback.answer("Права администратора выданы")
        await _render_user_detail(message, user_id)

    @router.callback_query(F.data.startswith("a:rev:"))
    @admin_access.require_access
    async def callback_revoke_admin_start(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:rev:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return
        await callback.answer()
        await message.edit_text(
            f"Снять права администратора у пользователя {user_id}?",
            reply_markup=confirm_revoke_admin_keyboard(user_id),
        )

    @router.callback_query(F.data.startswith("a:revc:"))
    @admin_access.require_access
    async def callback_revoke_admin_confirm(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:revc:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return

        async with role_lock:
            admin_ids = set(await storage.list_admin_users())
            if user_id not in admin_ids:
                await callback.answer("Пользователь уже не администратор", show_alert=True)
                await _render_user_detail(message, user_id)
                return
            if len(admin_ids) <= 1:
                await callback.answer(
                    "Нельзя снять права у последнего администратора",
                    show_alert=True,
                )
                return
            await storage.remove_user_admin(user_id)
            admin_access.remove_user(user_id)

        await callback.answer("Права администратора сняты")
        await _render_user_detail(message, user_id)

    @router.callback_query(F.data.startswith("a:rm:"))
    @admin_access.require_access
    async def callback_remove_user_start(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:rm:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return
        await callback.answer()
        await message.edit_text(
            f"Удалить пользователя {user_id}?\n\nОн сразу потеряет доступ к боту.",
            reply_markup=confirm_remove_user_keyboard(user_id),
        )

    @router.callback_query(F.data.startswith("a:rmc:"))
    @admin_access.require_access
    async def callback_remove_user_confirm(callback: CallbackQuery) -> None:
        data = callback.data or ""
        user_id = _parse_telegram_user_id(data.removeprefix("a:rmc:"))
        message = editable_callback_message(callback)
        if user_id is None or message is None:
            await callback.answer("Некорректный пользователь", show_alert=True)
            return

        async with role_lock:
            if not await storage.is_user_allowed(user_id):
                await callback.answer("Пользователь уже удалён", show_alert=True)
                await _render_user_list(message)
                return
            admin_ids = set(await storage.list_admin_users())
            if user_id in admin_ids and len(admin_ids) <= 1:
                await callback.answer("Нельзя удалить последнего администратора", show_alert=True)
                return
            await storage.remove_user(user_id)
            if access is not None:
                access.remove_user(user_id)
            admin_access.remove_user(user_id)

        await callback.answer("Пользователь удалён")
        await _render_user_list(message)

    @router.callback_query(F.data == "a:auth")
    @admin_access.require_access
    async def callback_admin_auth(callback: CallbackQuery) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        phone = client.phone
        if not phone:
            await callback.answer()
            await message.edit_text(
                "Номер телефона Domonap не настроен.",
                reply_markup=back_keyboard("a:panel"),
            )
            return
        await callback.answer("Запрашиваю SMS…")
        try:
            success = await client.login(phone)
        except NetworkError:
            await message.edit_text(
                "Сеть недоступна. Повторите позже.",
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
            digits = "".join(char for char in phone if char.isdigit())
            masked = digits[:3] + "***" + digits[-2:] if len(digits) >= 4 else digits
            if phone.startswith("+"):
                masked = f"+{masked}"
            await message.edit_text(
                f"SMS отправлена на {masked}. Введите код командой /code <код>.",
                reply_markup=back_keyboard("a:panel"),
            )
        else:
            await message.edit_text(
                "Не удалось запросить SMS.", reply_markup=back_keyboard("a:panel")
            )

    @router.callback_query(F.data == "a:logout")
    @admin_access.require_access
    async def callback_admin_logout(callback: CallbackQuery) -> None:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        await callback.answer()
        await client.token_storage.clear()
        client.mark_session_expired("admin logout")
        await message.edit_text(
            "✅ Сессия Domonap завершена.", reply_markup=back_keyboard("a:panel")
        )
