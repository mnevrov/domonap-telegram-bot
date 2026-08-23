import asyncio
import time
from pathlib import Path

HEARTBEAT_PATH = Path("/tmp/domonap-bot-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 10.0
HEARTBEAT_MAX_AGE_SECONDS = 45.0


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
) -> None:
    while True:
        path.write_text(str(time.time()), encoding="utf-8")
        await asyncio.sleep(interval_seconds)


def main() -> int:
    return 0 if heartbeat_is_fresh() else 1


if __name__ == "__main__":
    raise SystemExit(main())
