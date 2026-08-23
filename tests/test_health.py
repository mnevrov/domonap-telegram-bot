import asyncio
import time
from contextlib import suppress

from domonap_bot.health import clear_heartbeat, heartbeat_is_fresh, run_heartbeat


def test_fresh_heartbeat_is_healthy(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    path.write_text(str(time.time()), encoding="utf-8")

    assert heartbeat_is_fresh(path, max_age_seconds=5.0)


def test_stale_or_future_heartbeat_is_unhealthy(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    path.write_text(str(time.time() - 60.0), encoding="utf-8")
    assert not heartbeat_is_fresh(path, max_age_seconds=5.0)

    path.write_text(str(time.time() + 60.0), encoding="utf-8")
    assert not heartbeat_is_fresh(path, max_age_seconds=5.0)


def test_missing_or_malformed_heartbeat_is_unhealthy(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    assert not heartbeat_is_fresh(path)

    path.write_text("not-a-timestamp", encoding="utf-8")
    assert not heartbeat_is_fresh(path)


def test_clear_heartbeat_removes_marker(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    path.write_text(str(time.time()), encoding="utf-8")

    clear_heartbeat(path)

    assert not path.exists()


async def test_run_heartbeat_updates_marker(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    task = asyncio.create_task(run_heartbeat(path, interval_seconds=0.01))
    try:
        await asyncio.sleep(0.03)
        assert heartbeat_is_fresh(path, max_age_seconds=1.0)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
