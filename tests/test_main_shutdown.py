import asyncio

import pytest

from domonap_bot import main as main_module


@pytest.mark.asyncio
async def test_bounded_close_times_out_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = asyncio.Event()

    async def hangs() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(main_module, "_SHUTDOWN_TIMEOUT", 0.01)

    await main_module._bounded_close("test resource", hangs)

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_bounded_close_contains_component_error() -> None:
    async def fails() -> None:
        raise RuntimeError("boom")

    await main_module._bounded_close("test resource", fails)


@pytest.mark.asyncio
async def test_cancel_task_cancels_running_task() -> None:
    cancelled = asyncio.Event()

    async def worker() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)

    await main_module._cancel_task(task)

    assert task.cancelled()
    assert cancelled.is_set()
