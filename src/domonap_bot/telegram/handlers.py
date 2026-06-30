import logging
from time import monotonic

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import (
    DomonapError,
    NetworkError,
    SessionExpiredError,
    TokenExpiredError,
)
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.keyboards import door_selection_keyboard

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 5


class CooldownManager:
    def __init__(self, timeout: float = _COOLDOWN_SECONDS) -> None:
        self._cooldowns: dict[tuple[int, str], float] = {}
        self._timeout = timeout

    def is_ready(self, user_id: int, door_id: str) -> bool:
        last = self._cooldowns.get((user_id, door_id))
        if last is None:
            return True
        return monotonic() - last >= self._timeout

    def set(self, user_id: int, door_id: str) -> None:
        self._cooldowns[(user_id, door_id)] = monotonic()

    def remaining(self, user_id: int, door_id: str) -> float:
        last = self._cooldowns.get((user_id, door_id))
        if last is None:
            return 0.0
        return max(0.0, self._timeout - (monotonic() - last))

    def clear_expired(self) -> int:
        now = monotonic()
        expired = [k for k, t in self._cooldowns.items() if now - t >= self._timeout]
        for k in expired:
            del self._cooldowns[k]
        return len(expired)


def _describe_error(exc: DomonapError) -> str:
    if isinstance(exc, (TokenExpiredError, SessionExpiredError)):
        return "Session expired. Re-authentication required."
    if isinstance(exc, NetworkError):
        return "Network unavailable. Please try again later."
    return f"API error: {exc}"


def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
) -> None:
    cooldown = CooldownManager()

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

    @router.message(Command("start"))
    @access.require_access
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "🏠 Domonap Bot\n\n"
            "Commands:\n"
            "/status — connection & auth status\n"
            "/doors — list available doors\n"
            "/open — choose a door to open"
        )

    @router.message(Command("status"))
    @access.require_access
    async def cmd_status(message: Message) -> None:
        has_token = await client.token_storage.load()
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
                await callback.message.edit_text(_describe_error(exc))
            else:
                await callback.answer(_describe_error(exc), show_alert=True)
            return

        text = "✅ Door opened successfully!" if success else "❌ Failed to open door."

        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(text)
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
