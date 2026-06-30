import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.exceptions import DomonapError, TokenExpiredError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.keyboards import door_selection_keyboard

logger = logging.getLogger(__name__)


def register_handlers(
    router: Router,
    client: DomonapClient,
    access: AccessControl,
) -> None:
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
        lines = [
            f"Authenticated: {'✅' if has_token else '❌'}",
            f"Phone: {client.phone or 'not set'}",
        ]
        await message.answer("\n".join(lines))

    @router.message(Command("doors"))
    @access.require_access
    async def cmd_doors(message: Message) -> None:
        try:
            doors = await client.get_doors()
        except TokenExpiredError:
            await message.answer("Session expired. Re-authentication required.")
            return
        except DomonapError as exc:
            await message.answer(f"Error fetching doors: {exc}")
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
            await message.answer(f"Error fetching doors: {exc}")
            return

        if not doors:
            await message.answer("No doors available.")
            return

        await message.answer(
            "Select a door to open:",
            reply_markup=door_selection_keyboard(doors),
        )

    @router.callback_query(F.data.startswith("open:"))
    @access.require_access
    async def callback_open_door(callback: CallbackQuery) -> None:
        door_id = callback.data.removeprefix("open:")
        try:
            success = await client.open_door(door_id)
        except DomonapError as exc:
            await callback.message.edit_text(f"Error: {exc}")
            return

        if success:
            text = "✅ Door opened successfully!"
        else:
            text = "❌ Failed to open door."

        await callback.message.edit_text(text)
