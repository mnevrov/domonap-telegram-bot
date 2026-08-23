import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

logger = logging.getLogger(__name__)

_PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="open", description="Открыть дверь"),
    BotCommand(command="doors", description="Список дверей"),
    BotCommand(command="status", description="Статус Domonap"),
    BotCommand(command="help", description="Помощь"),
]


async def configure_bot_commands(bot: Bot) -> bool:
    """Best-effort command menu setup; polling must not depend on this cosmetic call."""
    try:
        await bot.set_my_commands(
            _PRIVATE_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
    except TelegramAPIError as exc:
        logger.warning("Failed to configure Telegram command menu: %s", exc)
        return False
    return True
