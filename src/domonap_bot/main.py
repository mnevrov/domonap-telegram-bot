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
        logger.warning(
            "ALLOWED_TELEGRAM_USER_IDS is empty — the bot is open to ALL Telegram "
            "users. Set this in .env to restrict access."
        )

    storage = SqliteStorage(settings.storage_path_resolved)
    await storage.initialize()

    token_storage = TokenStorage(storage)
    client = DomonapClient(token_storage, phone=settings.domonap_phone)
    restored = await client.hydrate_from_storage()
    logger.info("Session restored from storage: %s", restored)

    bot, dp = build_bot(settings, client)

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
