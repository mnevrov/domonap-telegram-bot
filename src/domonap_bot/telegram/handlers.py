import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import (
    ApiError,
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.domonap.models import AuthSession, DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.cooldown import CooldownManager
from domonap_bot.telegram.errors import describe_error as _describe_error
from domonap_bot.telegram.keyboards import back_keyboard, door_selection_keyboard

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
            if target.message and hasattr(target.message, "edit_text"):
                await target.message.edit_text(msg)
            else:
                await target.answer(msg, show_alert=True)
        else:
            await target.answer(msg)

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
            lines = [
                "Authenticated: ✅",
                f"Phone: {client.phone or 'not set'}",
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

        text = "Available doors:\n" + "\n".join(
            f"🚪 {d.name}" for d in doors
        )
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
                f"SMS code sent to {masked}\n"
                f"Use /code <code> to complete authorization."
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

        if success:
            await message.answer("✅ Successfully authorized with Domonap!")
        else:
            await message.answer("❌ Invalid code or session expired. Run /auth again.")

        try:
            await message.delete()
        except Exception:
            pass

    @router.message(Command("logout"))
    @admin_access.require_access
    async def cmd_logout(message: Message) -> None:
        await client.token_storage.clear()
        client.mark_session_expired("user logout")
        await message.answer("✅ Tokens cleared. Logged out.")

    @router.message(Command("import_tokens"))
    @admin_access.require_access
    async def cmd_import_tokens(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(
                "Usage: /import_tokens <access_token> <refresh_token>\n\n"
                "Example: /import_tokens eyJhbG... eyJjbG..."
            )
            return

        access_token = parts[1].strip()
        refresh_token = parts[2].strip()

        if not access_token or not refresh_token:
            await message.answer("Tokens cannot be empty.")
            return

        client.set_tokens(access_token, refresh_token, None)
        session = AuthSession(
            access_token=access_token,
            refresh_token=refresh_token,
            phone=client.phone,
            device_token=client.device_token,
            instance_id=client.instance_id,
        )
        await client.token_storage.save(session)

        try:
            await message.delete()
        except Exception:
            pass

        await message.answer("✅ Tokens imported successfully. Use /status to verify.")

    @router.callback_query(F.data.startswith("open:"))
    @access.require_access
    async def callback_open_door(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Invalid callback data", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        door_id = callback.data.removeprefix("open:")

        if not cooldown.is_ready(user_id, door_id):
            remaining = cooldown.remaining(user_id, door_id)
            await callback.answer(
                f"Please wait {remaining:.0f}s before retrying",
                show_alert=True,
            )
            return

        await callback.answer("Opening door...")
        cooldown.set(user_id, door_id)

        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            if callback.message and hasattr(callback.message, "edit_text"):
                await callback.message.edit_text(_describe_error(exc), reply_markup=back_keyboard("m:main"))
            else:
                await callback.answer(_describe_error(exc), show_alert=True)
            return

        text = "✅ Door opened successfully!" if success else "❌ Failed to open door."

        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(text, reply_markup=back_keyboard("m:main"))
        else:
            await callback.answer(text, show_alert=True)

    @router.callback_query(F.data.startswith("answer:"))
    @access.require_access
    async def callback_answer_call(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Invalid callback data", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        call_id = callback.data.removeprefix("answer:")
        cooldown_key = f"answer:{call_id}"

        if not cooldown.is_ready(user_id, cooldown_key):
            remaining = cooldown.remaining(user_id, cooldown_key)
            await callback.answer(
                f"Please wait {remaining:.0f}s before retrying",
                show_alert=True,
            )
            return

        await callback.answer("Answering call...")
        cooldown.set(user_id, cooldown_key)

        try:
            success = await client.answer_call(call_id)
        except DomonapError as exc:
            await _respond_error(callback, exc)
            return

        text = "📞 Call answered." if success else "❌ Failed to answer call."
        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(text, reply_markup=back_keyboard("m:main"))
        else:
            await callback.answer(text, show_alert=True)

    @router.callback_query(F.data.startswith("reject:"))
    @access.require_access
    async def callback_end_call(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Invalid callback data", show_alert=True)
            return
        user_id = callback.from_user.id if callback.from_user else 0
        call_id = callback.data.removeprefix("reject:")
        cooldown_key = f"reject:{call_id}"

        if not cooldown.is_ready(user_id, cooldown_key):
            remaining = cooldown.remaining(user_id, cooldown_key)
            await callback.answer(
                f"Please wait {remaining:.0f}s before retrying",
                show_alert=True,
            )
            return

        await callback.answer("Ending call...")
        cooldown.set(user_id, cooldown_key)

        try:
            success = await client.end_call(call_id)
        except DomonapError as exc:
            await _respond_error(callback, exc)
            return

        text = "🔴 Call ended." if success else "❌ Failed to end call."
        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(text, reply_markup=back_keyboard("m:main"))
        else:
            await callback.answer(text, show_alert=True)


async def _auto_open_door(
    message: Message,
    door: DoorKey,
    user_id: int,
    client: DomonapClient,
    cooldown: CooldownManager,
) -> None:
    if not cooldown.is_ready(user_id, door.id):
        remaining = cooldown.remaining(user_id, door.id)
        await message.answer(
            f"Please wait {remaining:.0f}s before opening this door again."
        )
        return

    cooldown.set(user_id, door.id)

    try:
        success = await client.open_door(door.id)
    except DomonapError as exc:
        await message.answer(_describe_error(exc))
        return

    if success:
        await message.answer(f"✅ Door '{door.name}' opened successfully!")
    else:
        await message.answer(f"❌ Failed to open door '{door.name}'.")
