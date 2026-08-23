import asyncio
import logging

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.health import clear_heartbeat, run_heartbeat
from domonap_bot.logging_config import setup_logging
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.storage.tokens import TokenStorage
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.bot import build_bot
from domonap_bot.telegram.call_watcher import CallWatcher

logger = logging.getLogger(__name__)


async def main() -> None:
    clear_heartbeat()

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
    client = DomonapClient(
        token_storage,
        phone=settings.domonap_phone,
        register_device_token=settings.domonap_register_device_token,
    )
    restored = await client.hydrate_from_storage()
    logger.info("Session restored from storage: %s", restored)
    logger.info(
        "Domonap device-token registration: %s",
        "enabled" if settings.domonap_register_device_token else "disabled",
    )

    access = AccessControl(settings.allowed_telegram_user_ids)
    bot, dp = await build_bot(settings, client, storage, access=access)

    watcher = CallWatcher(client, bot, settings, access=access)
    await watcher.start()
    heartbeat_task = asyncio.create_task(run_heartbeat())

    try:
        logger.info("Starting bot polling")
        await dp.start_polling(bot)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        clear_heartbeat()
        await watcher.stop()
        await client.close()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
