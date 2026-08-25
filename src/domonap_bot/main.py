import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot

from domonap_bot.config import Settings
from domonap_bot.domonap.client import DomonapClient
from domonap_bot.domonap.compatibility import RuntimeCompatibilityMonitor
from domonap_bot.domonap.models import AuthSession
from domonap_bot.health import (
    HeartbeatWatchdog,
    clear_heartbeat,
    run_heartbeat,
)
from domonap_bot.logging_config import setup_logging
from domonap_bot.storage.sqlite import SqliteStorage
from domonap_bot.storage.tokens import TokenStorage, TokenStorageEncryptionError
from domonap_bot.telegram.access import AccessControl
from domonap_bot.telegram.bot import build_bot
from domonap_bot.telegram.call_watcher import CallWatcher
from domonap_bot.telegram.commands import configure_bot_commands
from domonap_bot.web.camera_proxy import CameraProxy, start_camera_proxy, stop_camera_proxy

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


def _bind_session_invalidation_persistence(
    client: DomonapClient,
    token_storage: TokenStorage,
    pending_tasks: set[asyncio.Task[None]],
) -> None:
    """Persist terminal session invalidation without widening the client API.

    Successful login/refresh paths already save the complete session before invoking
    ``token_update_callback``. The callback is therefore only responsible for the
    empty-session transition emitted by ``DomonapClient._invalidate_refresh``.
    """

    def on_token_update(session: AuthSession) -> None:
        if session.access_token or session.refresh_token:
            return

        task = asyncio.create_task(token_storage.clear())
        pending_tasks.add(task)

        def on_done(done: asyncio.Task[None]) -> None:
            pending_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.error(
                    "Failed to clear invalidated Domonap session from storage: %s",
                    error,
                )

        task.add_done_callback(on_done)

    client.token_update_callback = on_token_update


async def _drain_persistence_tasks(tasks: set[asyncio.Task[None]]) -> None:
    if not tasks:
        return
    try:
        async with asyncio.timeout(_SHUTDOWN_TIMEOUT):
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
    except TimeoutError:
        logger.error("Timed out while persisting terminal Domonap session state")


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

    storage_encryption_key = (
        settings.storage_encryption_key.get_secret_value().strip()
        if settings.storage_encryption_key is not None
        else ""
    )
    if not storage_encryption_key:
        logger.error(
            "STORAGE_ENCRYPTION_KEY is empty — refusing to start. "
            "Generate a Fernet key and store it separately from the SQLite database."
        )
        return

    storage = SqliteStorage(settings.storage_path_resolved)
    client: DomonapClient | None = None
    bot: Bot | None = None
    watcher: CallWatcher | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    watchdog: HeartbeatWatchdog | None = None
    compatibility_monitor: RuntimeCompatibilityMonitor | None = None
    camera_proxy: CameraProxy | None = None
    camera_proxy_runner = None
    persistence_tasks: set[asyncio.Task[None]] = set()

    try:
        await storage.initialize()

        try:
            token_storage = TokenStorage(storage, encryption_key=storage_encryption_key)
        except ValueError as exc:
            logger.error("Invalid storage encryption key: %s", exc)
            return

        client = DomonapClient(
            token_storage,
            phone=settings.domonap_phone,
            register_device_token=settings.domonap_register_device_token,
        )
        _bind_session_invalidation_persistence(client, token_storage, persistence_tasks)

        compatibility_monitor = RuntimeCompatibilityMonitor()
        compatibility_monitor.attach(client._http)
        logger.info(
            "Domonap runtime compatibility monitor enabled: profile=%s",
            compatibility_monitor.report()["profile"]["name"],
        )

        camera_secret = (
            settings.camera_proxy_secret.get_secret_value().strip()
            if settings.camera_proxy_secret is not None
            else ""
        )
        if settings.public_base_url and camera_secret:
            try:
                camera_proxy = CameraProxy(
                    client,
                    public_base_url=settings.public_base_url,
                    secret=camera_secret,
                    link_ttl_seconds=settings.camera_link_ttl_seconds,
                )
                camera_proxy_runner = await start_camera_proxy(
                    camera_proxy, "0.0.0.0", settings.camera_proxy_port
                )
                logger.info("Camera proxy listening on port %s", settings.camera_proxy_port)
            except ValueError as exc:
                logger.error("Camera proxy disabled: %s", exc)
        elif settings.public_base_url or camera_secret:
            logger.warning(
                "Camera proxy disabled: PUBLIC_BASE_URL and CAMERA_PROXY_SECRET are both required"
            )

        try:
            restored = await client.hydrate_from_storage()
        except TokenStorageEncryptionError as exc:
            logger.error("Cannot restore encrypted Domonap session: %s", exc)
            return
        logger.info("Session restored from storage: %s", restored)
        logger.info(
            "Domonap device-token registration: %s",
            "enabled" if settings.domonap_register_device_token else "disabled",
        )

        access = AccessControl(settings.allowed_telegram_user_ids)
        bot, dp = await build_bot(
            settings,
            client,
            storage,
            access=access,
            camera_url_provider=camera_proxy.url_for if camera_proxy else None,
        )
        await configure_bot_commands(bot)

        watcher = CallWatcher(
            client,
            bot,
            settings,
            access=access,
            camera_url_provider=camera_proxy.url_for if camera_proxy else None,
        )
        await watcher.start()

        def runtime_is_healthy() -> bool:
            if not settings.call_watcher_enabled:
                return True
            task = watcher._task
            return task is not None and not task.done()

        heartbeat_task = asyncio.create_task(run_heartbeat(healthy=runtime_is_healthy))
        watchdog = HeartbeatWatchdog()
        watchdog.start()

        logger.info("Starting bot polling")
        await dp.start_polling(bot)
    finally:
        if watchdog is not None:
            watchdog.stop()
        await _cancel_task(heartbeat_task)
        clear_heartbeat()
        if watcher is not None:
            await _bounded_close("call watcher", watcher.stop)
        if camera_proxy_runner is not None:
            await _bounded_close("camera proxy", lambda: stop_camera_proxy(camera_proxy_runner))
        if bot is not None:
            await _bounded_close("Telegram bot session", bot.session.close)
        if client is not None:
            await _bounded_close("Domonap client", client.close)
        await _drain_persistence_tasks(persistence_tasks)
        await _bounded_close("storage", storage.close)


if __name__ == "__main__":
    asyncio.run(main())
