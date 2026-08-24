import asyncio
import threading
import time
from contextlib import suppress

from domonap_bot.health import (
    HeartbeatWatchdog,
    clear_heartbeat,
    heartbeat_is_fresh,
    run_heartbeat,
)


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


async def test_run_heartbeat_goes_unhealthy_when_component_fails(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    component_healthy = True

    def healthy() -> bool:
        return component_healthy

    task = asyncio.create_task(
        run_heartbeat(path, interval_seconds=0.01, healthy=healthy)
    )
    try:
        await asyncio.sleep(0.02)
        assert heartbeat_is_fresh(path, max_age_seconds=1.0)

        component_healthy = False
        await asyncio.sleep(0.02)
        assert not path.exists()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_watchdog_terminates_on_stale_heartbeat(tmp_path) -> None:
    path = tmp_path / "heartbeat"
    path.write_text(str(time.time() - 60.0), encoding="utf-8")
    terminated = threading.Event()
    exit_codes: list[int] = []

    def terminate(code: int) -> None:
        exit_codes.append(code)
        terminated.set()

    watchdog = HeartbeatWatchdog(
        path,
        max_age_seconds=0.01,
        startup_grace_seconds=0.0,
        poll_interval_seconds=0.01,
        terminate=terminate,
    )
    watchdog.start()
    try:
        assert terminated.wait(1.0)
        assert exit_codes == [1]
    finally:
        watchdog.stop()
