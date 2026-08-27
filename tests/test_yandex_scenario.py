import pytest

from domonap_bot.yandex.scenario import YandexScenarioAnnouncer


class FakeScenarioClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def run_scenario(self, scenario_id: str) -> str:
        self.calls.append(scenario_id)
        if self.fail:
            raise RuntimeError("ambiguous network failure")
        return "request-1"


@pytest.mark.asyncio
async def test_mapped_call_announced_once() -> None:
    client = FakeScenarioClient()
    announcer = YandexScenarioAnnouncer(  # type: ignore[arg-type]
        client,
        {"door-1": "scenario-1"},
    )

    assert await announcer.announce(call_id="call-1", door_id="door-1") is True
    assert await announcer.announce(call_id="call-1", door_id="door-1") is False
    assert client.calls == ["scenario-1"]


@pytest.mark.asyncio
async def test_unmapped_door_is_ignored() -> None:
    client = FakeScenarioClient()
    announcer = YandexScenarioAnnouncer(client, {})  # type: ignore[arg-type]

    assert await announcer.announce(call_id="call-1", door_id="door-1") is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_failed_delivery_is_not_retried_for_same_call() -> None:
    client = FakeScenarioClient(fail=True)
    announcer = YandexScenarioAnnouncer(  # type: ignore[arg-type]
        client,
        {"door-1": "scenario-1"},
    )

    assert await announcer.announce(call_id="call-1", door_id="door-1") is False
    assert await announcer.announce(call_id="call-1", door_id="door-1") is False
    assert client.calls == ["scenario-1"]
