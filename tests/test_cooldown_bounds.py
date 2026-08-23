import pytest

from domonap_bot.telegram import cooldown as cooldown_module
from domonap_bot.telegram.cooldown import CooldownManager


def test_capacity_pressure_purges_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(cooldown_module, "monotonic", lambda: now)
    monkeypatch.setattr(cooldown_module, "_MAX_COOLDOWN_ENTRIES", 2)
    manager = CooldownManager(timeout=5.0)
    manager.set(1, "old-a")
    manager.set(1, "old-b")

    now = 6.0
    manager.set(1, "new")

    assert manager.is_ready(1, "old-a") is True
    assert manager.is_ready(1, "old-b") is True
    assert list(manager._cooldowns) == [(1, "new")]


def test_cooldown_state_evicts_oldest_at_hard_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(cooldown_module, "monotonic", lambda: now)
    monkeypatch.setattr(cooldown_module, "_MAX_COOLDOWN_ENTRIES", 3)
    manager = CooldownManager(timeout=100.0)

    for action in ("a", "b", "c"):
        manager.set(1, action)
        now += 1.0

    manager.set(1, "d")

    assert len(manager._cooldowns) == 3
    assert (1, "a") not in manager._cooldowns
    assert set(manager._cooldowns) == {(1, "b"), (1, "c"), (1, "d")}
