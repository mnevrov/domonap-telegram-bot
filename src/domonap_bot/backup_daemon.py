from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from domonap_bot.storage_tools import backup_database

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_PATH = Path("data/storage.db")
_DEFAULT_BACKUP_DIR = Path("/app/backups")
_DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
_DEFAULT_RETENTION_COUNT = 28
_MISSING_SOURCE_RETRY_SECONDS = 60


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def prune_backups(directory: Path, *, retention_count: int) -> list[Path]:
    backups = sorted(
        (path for path in directory.glob("storage-*.db") if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
    removed: list[Path] = []
    for path in backups[retention_count:]:
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def create_backup_once(
    source: Path,
    directory: Path,
    *,
    retention_count: int,
    now: datetime | None = None,
) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    destination = directory / f"storage-{timestamp}.db"
    backup_database(source, destination)
    removed = prune_backups(directory, retention_count=retention_count)
    logger.info(
        "SQLite backup created: %s; retained=%s; pruned=%s",
        destination,
        retention_count,
        len(removed),
    )
    return destination


def run_forever() -> None:
    source = Path(os.getenv("STORAGE_PATH", str(_DEFAULT_STORAGE_PATH))).resolve()
    directory = Path(os.getenv("BACKUP_DIR", str(_DEFAULT_BACKUP_DIR))).resolve()
    interval_seconds = _positive_int("BACKUP_INTERVAL_SECONDS", _DEFAULT_INTERVAL_SECONDS)
    retention_count = _positive_int("BACKUP_RETENTION_COUNT", _DEFAULT_RETENTION_COUNT)

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info(
        "Starting SQLite backup service: source=%s directory=%s interval=%ss retention=%s",
        source,
        directory,
        interval_seconds,
        retention_count,
    )

    while True:
        try:
            create_backup_once(
                source,
                directory,
                retention_count=retention_count,
            )
        except FileNotFoundError:
            logger.warning("SQLite source is not available yet: %s", source)
            time.sleep(min(interval_seconds, _MISSING_SOURCE_RETRY_SECONDS))
            continue
        except Exception:
            logger.exception("SQLite backup failed")
            time.sleep(min(interval_seconds, _MISSING_SOURCE_RETRY_SECONDS))
            continue
        time.sleep(interval_seconds)


def main() -> None:
    run_forever()


if __name__ == "__main__":
    main()
