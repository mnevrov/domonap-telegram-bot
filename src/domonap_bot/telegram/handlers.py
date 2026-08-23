import logging

from aiogram import F, Router
from aiogram.filters import Command
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
from domonap_bot.telegram.callback_utils import editable_callback_message
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


def _mask_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 4:
        return phone
    masked = digits[:3] + "***" + digits[-2:]
    if phone.startswith("+"):
        return f"+{masked}"
    return masked


def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
    admin_access: AccessControl,
    cooldown: CooldownManager,
) -> None:
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

    @router.message(Command("status"))
    @access.require_access
    async def cmd_status(message: Message) -> None:
        has_token = client.access_token or client.refresh_token
        if not has_token:
            await message.answer(
                "Authenticated: ❌\n"
                "No tokens stored. Authentication required."
            )
            return

        if client.has_valid_refresh_token():
            refreshed = await client.refresh_session()
            if not refreshed:
                await message.answer(
                    "Authenticated: ❌\n"
                    "Token refresh failed. Re-authentication required."
                )
                return

        try:
            username = await client.get_username()
            phone = _mask_phone(client.phone) if client.phone else "not set"
            lines = [
                "Authenticated: ✅",
                f"Phone: {phone}",
            ]
            if username:
                lines.append(f"Username: {username}")
            await message.answer("\n".join(lines))
        except (TokenExpiredError, SessionExpiredError):
            await message.answer(
                "Authenticated: ❌\n"
                "Session expired. Re-authentication required."
            )
        except NetworkError:
            await message.answer(
                "Authenticated: ❓\n"
                "Network unavailable. Cannot verify status."
            )
        except DomonapError:
            await message.answer(
                "Authenticated: ❓\n"
                "API error. Cannot verify status."
            )

    @router.message(Command("doors"))
    @access.require_access
    async def cmd_doors(message: Message) -> None:
        try:
            doors = await client.get_doors()
        except DomonapError as exc:
            await _respond_error(message, exc)
            return

        if not doors:
            await message.answer("No doors available.")
            return

        text = "Available doors:\n" + "\n".join(f"🚪 {door.name}" for door in doors)
        kb = door_selection_keyboard(doors)
        await message.answer(text, reply_markup=kb)

    @router.message(Command("open"))
    @access.require_access
    async def cmd_open(message: Message) -> None:
        try:
            doors = await client.get_doors()
        except DomonapError as exc:
            await _respond_error(message, exc)
            return

        if not doors:
            await message.answer("No doors available. Add a key in the Domonap app first.")
            return

        if len(doors) == 1:
            door = doors[0]
            user_id = message.from_user.id if message.from_user else 0
            await _auto_open_door(message, door, user_id, client, cooldown)
            return

        await message.answer(
            "Select a door to open:",
            reply_markup=door_selection_keyboard(doors),
        )

    @router.message(Command("auth"))
    @admin_access.require_access
    async def cmd_auth(message: Message) -> None:
        phone = client.phone
        if not phone:
            await message.answer("No phone number configured. Set DOMONAP_PHONE in .env")
            return

        try:
            success = await client.login(phone)
        except NetworkError:
            await message.answer("Network unavailable. Please try again later.")
            return
        except DomonapError as exc:
            logger.warning("SMS request failed for phone %s: %s", _mask_phone(phone), exc)
            await message.answer(_describe_error(exc))
            return

        if success:
            masked = _mask_phone(phone)
            await message.answer(
                f"SMS code sent to {masked}\nUse /code <code> to complete authorization."
            )
        else:
            await message.answer("Failed to request SMS code. Check phone number.")

    @router.message(Command("code"))
    @admin_access.require_access
    async def cmd_code(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer("Usage: /code <sms_code>")
            return

        code = parts[1].strip()

        try:
            success = await client.confirm_login(code)
        except NetworkError:
            await message.answer("Network unavailable. Please try again later.")
            return
        except DomonapError:
            await message.answer("Authorization failed. Check the code and try again.")
            return
        finally:
            try:
                await message.delete()
            except Exception:
                pass

        if success:
            await message.answer("✅ Successfully authorized with Domonap!")
        else:
            await message.answer("❌ Invalid code or session expired. Run /auth again.")

    @router.message(Command("logout"))
    @admin_access.require_access
    async def cmd_logout(message: Message) -> None:
        await client.token_storage.clear()
        client.mark_session_expired("user logout")
        await message.answer("✅ Tokens cleared. Logged out.")

    @router.callback_query(F.data.startswith("open:"))
    @access.require_access
    async def callback_open_door(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        door_id = callback.data.removeprefix("open:")

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
            await _respond_error(callback, exc)
            return

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
        call_id = callback.data.removeprefix("answer:")
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
            await _respond_error(callback, exc)
            return

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
        call_id = callback.data.removeprefix("reject:")
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
            await _respond_error(callback, exc)
            return

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
            f"Please wait {remaining:.0f}s before opening this door again."
        )
        return

    cooldown.set(user_id, door_id)

    try:
        success = await client.open_door(door_id)
    except DomonapError as exc:
        await message.answer(_describe_error(exc))
        return

    if success:
        await message.answer(f"✅ Door '{door.name}' opened successfully!")
    else:
        await message.answer(f"❌ Failed to open door '{door.name}'.")
