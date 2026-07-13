import asyncio
import logging

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.logging_config import setup_logging
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.storage.tokens import TokenStorage
from domonap_bot.telegram.bot import build_bot
from domonap_bot.telegram.call_watcher import CallWatcher

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    setup_logging(settings.log_level)

    if not settings.allowed_telegram_user_ids:
        logger.error(
            "ALLOWED_TELEGRAM_USER_IDS is empty — refusing to start. "
            "Set at least one Telegram user ID in .env to restrict access."
        )
        return

    storage = SqliteStorage(settings.storage_path_resolved)
    await storage.initialize()

    token_storage = TokenStorage(storage)
    client = DomonapClient(token_storage, phone=settings.domonap_phone)
    restored = await client.hydrate_from_storage()
    logger.info("Session restored from storage: %s", restored)

    bot, dp = await build_bot(settings, client, storage)

    watcher = CallWatcher(client, bot, settings)
    await watcher.start()

    try:
        logger.info("Starting bot polling")
        await dp.start_polling(bot)
    finally:
        await watcher.stop()
        await client.close()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
