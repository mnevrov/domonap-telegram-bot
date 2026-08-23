from unittest.mock import AsyncMock, MagicMock

from aiogram import Bot
from aiogram.types import BotCommandScopeAllPrivateChats

from domonap_bot.telegram.commands import configure_bot_commands


async def test_command_menu_is_compact_and_russian() -> None:
    bot = MagicMock(spec=Bot)
    bot.set_my_commands = AsyncMock()

    result = await configure_bot_commands(bot)

    assert result is True
    bot.set_my_commands.assert_awaited_once()
    commands = bot.set_my_commands.await_args.args[0]
    scope = bot.set_my_commands.await_args.kwargs["scope"]
    assert isinstance(scope, BotCommandScopeAllPrivateChats)
    assert [command.command for command in commands] == [
        "start",
        "open",
        "doors",
        "status",
        "help",
    ]
    assert all(command.description for command in commands)
    assert not any(command.command in {"auth", "logout", "code"} for command in commands)
