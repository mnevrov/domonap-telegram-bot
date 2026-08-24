import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

HEARTBEAT_PATH = Path("/tmp/domonap-bot-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 10.0
HEARTBEAT_MAX_AGE_SECONDS = 45.0
WATCHDOG_STARTUP_GRACE_SECONDS = 60.0
WATCHDOG_POLL_INTERVAL_SECONDS = 5.0

logger = logging.getLogger(__name__)


def clear_heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    path.unlink(missing_ok=True)


def heartbeat_is_fresh(
    path: Path = HEARTBEAT_PATH,
    *,
    max_age_seconds: float = HEARTBEAT_MAX_AGE_SECONDS,
) -> bool:
    try:
        heartbeat_at = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False

    age = time.time() - heartbeat_at
    return 0.0 <= age <= max_age_seconds


async def run_heartbeat(
    path: Path = HEARTBEAT_PATH,
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    healthy: Callable[[], bool] | None = None,
) -> None:
    while True:
        if healthy is None or healthy():
            path.write_text(str(time.time()), encoding="utf-8")
        else:
            clear_heartbeat(path)
        await asyncio.sleep(interval_seconds)


class HeartbeatWatchdog:
    """Process-level watchdog that survives an asyncio event-loop stall.

    Docker marks the container unhealthy when the heartbeat goes stale, but Docker
    Compose does not restart a running process merely because its health status is
    ``unhealthy``. This daemon thread converts a stale heartbeat into process exit so
    ``restart: unless-stopped`` can recover the service automatically.
    """

    def __init__(
        self,
        path: Path = HEARTBEAT_PATH,
        *,
        max_age_seconds: float = HEARTBEAT_MAX_AGE_SECONDS,
        startup_grace_seconds: float = WATCHDOG_STARTUP_GRACE_SECONDS,
        poll_interval_seconds: float = WATCHDOG_POLL_INTERVAL_SECONDS,
        terminate: Callable[[int], None] = os._exit,
    ) -> None:
        self._path = path
        self._max_age_seconds = max_age_seconds
        self._startup_grace_seconds = startup_grace_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._terminate = terminate
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="heartbeat-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self._poll_interval_seconds * 2))

    def _run(self) -> None:
        if self._stop.wait(self._startup_grace_seconds):
            return
        while not self._stop.is_set():
            if not heartbeat_is_fresh(
                self._path,
                max_age_seconds=self._max_age_seconds,
            ):
                logger.critical(
                    "Runtime heartbeat is stale; terminating process for supervisor recovery"
                )
                self._terminate(1)
                return
            if self._stop.wait(self._poll_interval_seconds):
                return


def main() -> int:
    return 0 if heartbeat_is_fresh() else 1


if __name__ == "__main__":
    raise SystemExit(main())
