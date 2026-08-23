import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot

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

_SHUTDOWN_TIMEOUT = 10.0


async def _bounded_close(name: str, close: Callable[[], Awaitable[None]]) -> None:
    try:
        async with asyncio.timeout(_SHUTDOWN_TIMEOUT):
            await close()
    except TimeoutError:
        logger.error("Timed out while closing %s", name)
    except Exception:
        logger.exception("Failed to close %s", name)


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


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
    client: DomonapClient | None = None
    bot: Bot | None = None
    watcher: CallWatcher | None = None
    heartbeat_task: asyncio.Task[None] | None = None

    try:
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

        logger.info("Starting bot polling")
        await dp.start_polling(bot)
    finally:
        await _cancel_task(heartbeat_task)
        clear_heartbeat()
        if watcher is not None:
            await _bounded_close("call watcher", watcher.stop)
        if bot is not None:
            await _bounded_close("Telegram bot session", bot.session.close)
        if client is not None:
            await _bounded_close("Domonap client", client.close)
        await _bounded_close("storage", storage.close)


if __name__ == "__main__":
    asyncio.run(main())
