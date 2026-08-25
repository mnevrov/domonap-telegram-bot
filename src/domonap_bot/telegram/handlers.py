import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import (
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.auth_flow import (
    AuthStates,
    request_sms_code,
    submit_sms_code,
)
from domonap_bot.telegram.auth_flow import mask_phone as _mask_phone
from domonap_bot.telegram.callback_utils import editable_callback_message, resolve_callback_id
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.errors import describe_error as _describe_error
from domonap_bot.telegram.keyboards import door_selection_keyboard
from domonap_bot.telegram.ui.action_state import (
    append_status,
    mark_call_finished,
    mark_door_opened,
)
from domonap_bot.telegram.ui.renderer import edit_view
from domonap_bot.telegram.ui.views import View

logger = logging.getLogger(__name__)


def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
    bot: Bot | None = None,
    call_watcher_enabled: bool = True,
) -> None:
    async def _show_typing(message: Message) -> None:
        if bot is not None and message.chat is not None:
            await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    async def _respond_error(
        target: Message | CallbackQuery,
        exc: DomonapError,
    ) -> None:
        msg = _describe_error(exc)
        if isinstance(target, CallbackQuery):
            message = editable_callback_message(target)
            if message is not None:
                await edit_view(
                    message,
                    View(append_status(message, f"❌ {msg}"), message.reply_markup),
                )
            else:
                await target.answer(msg, show_alert=True)
        else:
            await target.answer(msg)

    async def _render_action_status(
        callback: CallbackQuery,
        status: str,
        *,
        keyboard: InlineKeyboardMarkup | None = None,
    ) -> bool:
        message = editable_callback_message(callback)
        if message is None:
            await callback.answer(status, show_alert=True)
            return False
        await edit_view(
            message,
            View(
                append_status(message, status),
                message.reply_markup if keyboard is None else keyboard,
            ),
        )
        return True

    @router.message(Command("help"))
    @access.require_access
    async def cmd_help(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        lines = [
            "ℹ️ Помощь",
            "",
            "/start — главное меню",
            "/open — быстро открыть дверь",
            "/doors — список дверей",
            "/status — проверить подключение Domonap",
            "/help — эта справка",
        ]
        if admin_access.is_allowed(user_id):
            lines.extend(
                [
                    "",
                    "Для администратора:",
                    "/auth — подключить Domonap по SMS",
                    "/logout — завершить сессию Domonap",
                    "Управление пользователями доступно из главного меню.",
                ]
            )
        await message.answer("\n".join(lines))

    @router.message(Command("status"))
    @access.require_access
    async def cmd_status(message: Message) -> None:
        await _show_typing(message)
        has_token = client.access_token or client.refresh_token
        if not has_token:
            await message.answer(
                "Domonap: ❌ не подключён\n"
                "Авторизация требуется. Администратор может использовать /auth."
            )
            return

        if client.has_valid_refresh_token():
            refreshed = await client.refresh_session()
            if not refreshed:
                await message.answer(
                    "Domonap: ❌ сессия истекла\n"
                    "Подключите Domonap заново через /auth."
                )
                return

        try:
            username = await client.get_username()
            phone = _mask_phone(client.phone) if client.phone else "не указан"
            lines = [
                "Domonap: ✅ подключён",
                f"Телефон: {phone}",
            ]
            if username:
                lines.append(f"Пользователь: {username}")
            try:
                door_count = len(await client.get_doors())
            except (DomonapError, TypeError):
                door_count = None
            if door_count is not None:
                lines.append(f"Дверей: {door_count}")
            lines.append(
                f"Уведомления о звонках: {'✅ включены' if call_watcher_enabled else '⏸ выключены'}"
            )
            await message.answer("\n".join(lines))
        except (TokenExpiredError, SessionExpiredError):
            await message.answer(
                "Domonap: ❌ сессия истекла\n"
                "Подключите Domonap заново через /auth."
            )
        except NetworkError:
            await message.answer(
                "Domonap: ❓ не удалось проверить\n"
                "Сеть недоступна. Повторите позже."
            )
        except DomonapError:
            await message.answer(
                "Domonap: ❓ не удалось проверить\n"
                "Ошибка Domonap API. Повторите позже."
            )

    @router.message(Command("doors"))
    @access.require_access
    async def cmd_doors(message: Message) -> None:
        await _show_typing(message)
        try:
            doors = await client.get_doors()
        except DomonapError as exc:
            await _respond_error(message, exc)
            return

        if not doors:
            await message.answer("Доступных дверей нет.")
            return

        await message.answer(
            "🚪 Двери\n\nВыберите дверь:",
            reply_markup=door_selection_keyboard(doors),
        )

    @router.message(Command("open"))
    @access.require_access
    async def cmd_open(message: Message) -> None:
        try:
            doors = await client.get_doors()
        except DomonapError as exc:
            await _respond_error(message, exc)
            return

        if not doors:
            await message.answer(
                "Доступных дверей нет. Добавьте ключ в приложении Domonap."
            )
            return

        if len(doors) == 1:
            door = doors[0]
            user_id = message.from_user.id if message.from_user else 0
            await _auto_open_door(message, door, user_id, client, cooldown)
            return

        await message.answer(
            "🔓 Какую дверь открыть?",
            reply_markup=door_selection_keyboard(doors),
        )

    @router.message(Command("auth"))
    @admin_access.require_access
    async def cmd_auth(message: Message, state: FSMContext) -> None:
        await request_sms_code(message, client, state)

    @router.message(Command("code"))
    @admin_access.require_access
    async def cmd_code(message: Message, state: FSMContext) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Использование: /code <код из SMS>")
            return
        await submit_sms_code(message, client, state, parts[1])

    @router.message(AuthStates.waiting_sms_code, Command("cancel"))
    @admin_access.require_access
    async def cancel_sms_code(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Авторизация отменена.")

    @router.message(AuthStates.waiting_sms_code, F.text)
    @admin_access.require_access
    async def receive_sms_code(message: Message, state: FSMContext) -> None:
        await submit_sms_code(message, client, state, message.text or "")

    @router.message(Command("logout"))
    @admin_access.require_access
    async def cmd_logout(message: Message, state: FSMContext) -> None:
        await state.clear()
        await client.token_storage.clear()
        client.mark_session_expired("user logout")
        await message.answer("✅ Сессия Domonap завершена.")

    @router.callback_query(F.data.startswith("open:"))
    @access.require_access
    async def callback_open_door(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        if editable_callback_message(callback) is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        door_id = resolve_callback_id(callback.data.removeprefix("open:"))

        if not cooldown.is_ready(user_id, door_id):
            remaining = cooldown.remaining(user_id, door_id)
            await callback.answer(
                f"Повторите через {remaining:.0f} с",
                show_alert=True,
            )
            return

        await callback.answer("Открываю…")
        cooldown.set(user_id, door_id)

        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            cooldown.clear(user_id, door_id)
            await _respond_error(callback, exc)
            return

        if not success:
            cooldown.clear(user_id, door_id)

        message = editable_callback_message(callback)
        keyboard = (
            mark_door_opened(message.reply_markup)
            if success and message is not None
            else None
        )
        status = "✅ Дверь открыта." if success else "❌ Не удалось открыть дверь."
        await _render_action_status(callback, status, keyboard=keyboard)

    @router.callback_query(F.data.startswith("answer:"))
    @access.require_access
    async def callback_answer_call(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        if editable_callback_message(callback) is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        call_id = resolve_callback_id(callback.data.removeprefix("answer:"))
        cooldown_key = f"answer:{call_id}"

        if not cooldown.is_ready(user_id, cooldown_key):
            remaining = cooldown.remaining(user_id, cooldown_key)
            await callback.answer(
                f"Повторите через {remaining:.0f} с",
                show_alert=True,
            )
            return

        await callback.answer("Отвечаю…")
        cooldown.set(user_id, cooldown_key)

        try:
            success = await client.answer_call(call_id)
        except DomonapError as exc:
            cooldown.clear(user_id, cooldown_key)
            await _respond_error(callback, exc)
            return

        if not success:
            cooldown.clear(user_id, cooldown_key)

        message = editable_callback_message(callback)
        keyboard = (
            mark_call_finished(
                message.reply_markup,
                text="✅ Звонок принят",
                style="success",
            )
            if success and message is not None
            else None
        )
        status = "✅ Звонок принят." if success else "❌ Не удалось ответить на звонок."
        await _render_action_status(callback, status, keyboard=keyboard)

    @router.callback_query(F.data.startswith("reject:"))
    @access.require_access
    async def callback_end_call(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        if editable_callback_message(callback) is None:
            await callback.answer("Сообщение недоступно", show_alert=True)
            return
        call_id = resolve_callback_id(callback.data.removeprefix("reject:"))
        cooldown_key = f"reject:{call_id}"

        if not cooldown.is_ready(user_id, cooldown_key):
            remaining = cooldown.remaining(user_id, cooldown_key)
            await callback.answer(
                f"Повторите через {remaining:.0f} с",
                show_alert=True,
            )
            return

        await callback.answer("Завершаю звонок…")
        cooldown.set(user_id, cooldown_key)

        try:
            success = await client.end_call(call_id)
        except DomonapError as exc:
            cooldown.clear(user_id, cooldown_key)
            await _respond_error(callback, exc)
            return

        if not success:
            cooldown.clear(user_id, cooldown_key)

        message = editable_callback_message(callback)
        keyboard = (
            mark_call_finished(
                message.reply_markup,
                text="🔴 Звонок завершён",
                style="danger",
            )
            if success and message is not None
            else None
        )
        status = "🔴 Звонок завершён." if success else "❌ Не удалось завершить звонок."
        await _render_action_status(callback, status, keyboard=keyboard)


async def _auto_open_door(
    message: Message,
    door: DoorKey,
    user_id: int,
    client: DomonapClient,
    cooldown: CooldownManager,
) -> None:
    door_id = door.door_id
    if not cooldown.is_ready(user_id, door_id):
        remaining = cooldown.remaining(user_id, door_id)
        await message.answer(
            f"Повторите открытие двери через {remaining:.0f} с."
        )
        return

    cooldown.set(user_id, door_id)

    try:
        success = await client.open_door(door_id)
    except DomonapError as exc:
        cooldown.clear(user_id, door_id)
        await message.answer(_describe_error(exc))
        return

    if not success:
        cooldown.clear(user_id, door_id)

    if success:
        await message.answer(f"✅ {door.name}: дверь открыта.")
    else:
        await message.answer(f"❌ {door.name}: не удалось открыть дверь.")
