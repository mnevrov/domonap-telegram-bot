import asyncio

import pytest

from domonap_bot.yandex.active_call import ActiveCallRegistry
from domonap_bot.yandex.smart_home import YandexSmartHomeService


class FakeDoorOpener:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls: list[str] = []

    async def open_door(self, door_id: str) -> bool:
        self.calls.append(door_id)
        return self.success


class RaisingDoorOpener(FakeDoorOpener):
    async def open_door(self, door_id: str) -> bool:
        self.calls.append(door_id)
        raise RuntimeError("ambiguous transport failure")


class BlockingDoorOpener(FakeDoorOpener):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def open_door(self, door_id: str) -> bool:
        self.calls.append(door_id)
        self.started.set()
        await self.release.wait()
        return True


def open_payload(device_id: str = "domonap-active-intercom") -> dict[str, object]:
    return {
        "devices": [
            {
                "id": device_id,
                "capabilities": [
                    {
                        "type": "devices.capabilities.on_off",
                        "state": {"instance": "on", "value": True},
                    }
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_no_active_call_fails_closed() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    response = await service.action("req-1", open_payload())

    result = response["payload"]["devices"][0]["action_result"]
    assert result["status"] == "ERROR"
    assert result["error_code"] == "DEVICE_UNREACHABLE"
    assert opener.calls == []


@pytest.mark.asyncio
async def test_real_mode_opens_only_active_door_once() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    first = await service.action("req-1", open_payload())
    second = await service.action("req-2", open_payload())

    assert first["payload"]["devices"][0]["action_result"]["status"] == "DONE"
    assert second["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert opener.calls == ["door-42"]


@pytest.mark.asyncio
async def test_duplicate_request_id_is_idempotent() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    first = await service.action("req-1", open_payload())
    duplicate = await service.action("req-1", open_payload())

    assert duplicate == first
    assert opener.calls == ["door-42"]


@pytest.mark.asyncio
async def test_concurrent_duplicate_request_is_serialized_and_reuses_response() -> None:
    opener = BlockingDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    first_task = asyncio.create_task(service.action("req-1", open_payload()))
    await asyncio.wait_for(opener.started.wait(), timeout=0.1)
    duplicate_task = asyncio.create_task(service.action("req-1", open_payload()))
    await asyncio.sleep(0)
    opener.release.set()

    first, duplicate = await asyncio.gather(first_task, duplicate_task)

    assert duplicate == first
    assert opener.calls == ["door-42"]


@pytest.mark.asyncio
async def test_explicit_failed_open_releases_claim_for_new_request() -> None:
    opener = FakeDoorOpener(success=False)
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    first = await service.action("req-1", open_payload())
    second = await service.action("req-2", open_payload())

    assert first["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert second["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert opener.calls == ["door-42", "door-42"]


@pytest.mark.asyncio
async def test_ambiguous_open_exception_consumes_call_and_prevents_retry() -> None:
    opener = RaisingDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    first = await service.action("req-1", open_payload())
    second = await service.action("req-2", open_payload())

    assert first["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert second["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert opener.calls == ["door-42"]


@pytest.mark.asyncio
async def test_ambiguous_multiple_calls_never_open() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-1")
    await registry.start("call-2", "door-2")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    response = await service.action("req-1", open_payload())

    assert response["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert opener.calls == []


@pytest.mark.asyncio
async def test_dry_run_consumes_call_without_touching_relay() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=True)

    first = await service.action("req-1", open_payload())
    second = await service.action("req-2", open_payload())

    assert first["payload"]["devices"][0]["action_result"]["status"] == "DONE"
    assert second["payload"]["devices"][0]["action_result"]["status"] == "ERROR"
    assert opener.calls == []


@pytest.mark.asyncio
async def test_unknown_device_and_close_action_are_rejected() -> None:
    opener = FakeDoorOpener()
    registry = ActiveCallRegistry()
    await registry.start("call-1", "door-42")
    service = YandexSmartHomeService(opener, registry, dry_run=False)

    unknown = await service.action("req-1", open_payload("other-device"))
    close_payload = open_payload()
    close_payload["devices"][0]["capabilities"][0]["state"]["value"] = False
    close = await service.action("req-2", close_payload)

    assert unknown["payload"]["devices"][0]["action_result"]["error_code"] == "DEVICE_NOT_FOUND"
    assert close["payload"]["devices"][0]["action_result"]["error_code"] == "INVALID_ACTION"
    assert opener.calls == []
