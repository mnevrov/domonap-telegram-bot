import asyncio
import logging

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.logging_config import setup_logging
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.storage.tokens import TokenStorage
from domonap_bot.telegram.bot import build_bot

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    setup_logging(settings.log_level)

    storage = SqliteStorage(settings.storage_path_resolved)
    await storage.initialize()

    token_storage = TokenStorage(storage)
    client = DomonapClient(token_storage, phone=settings.domonap_phone)

    bot, dp = build_bot(settings, client)

    try:
        logger.info("Starting bot polling")
        await dp.start_polling(bot)
    finally:
        await client.close()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
