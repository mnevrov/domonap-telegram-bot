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
async def test_failed_open_releases_claim_for_new_request() -> None:
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
