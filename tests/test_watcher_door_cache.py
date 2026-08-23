import time
from unittest.mock import AsyncMock, MagicMock

from domonap_bot.config import Settings
from domonap_bot.domonap.models import DoorKey
from domonap_bot.telegram.call_watcher import CallWatcher


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        allowed_telegram_user_ids=[1],
    )


def _watcher(client: MagicMock) -> CallWatcher:
    client.refresh_session = AsyncMock(return_value=True)
    bot = MagicMock()
    return CallWatcher(client, bot, _settings())


def _door(key_id: str, door_id: str, name: str) -> DoorKey:
    return DoorKey(id=key_id, doorId=door_id, name=name)


async def test_fresh_door_cache_does_not_reload() -> None:
    client = MagicMock()
    client.get_doors = AsyncMock(return_value=[])
    watcher = _watcher(client)
    watcher._door_map_loaded_at = time.monotonic()

    await watcher._ensure_door_map_fresh()

    client.get_doors.assert_not_awaited()


async def test_stale_door_cache_is_replaced_atomically() -> None:
    client = MagicMock()
    new_door = _door("key-new", "door-new", "New Door")
    client.get_doors = AsyncMock(return_value=[new_door])
    watcher = _watcher(client)
    old_door = _door("key-old", "door-old", "Old Door")
    watcher._door_map = {
        old_door.id: old_door,
        old_door.door_id: old_door,
    }
    watcher._door_map_loaded_at = 0.0

    await watcher._ensure_door_map_fresh()

    assert "door-old" not in watcher._door_map
    assert "key-old" not in watcher._door_map
    assert watcher._door_map["door-new"] is new_door
    assert watcher._door_map["key-new"] is new_door


async def test_failed_refresh_preserves_previous_door_cache() -> None:
    client = MagicMock()
    client.get_doors = AsyncMock(side_effect=RuntimeError("temporary failure"))
    watcher = _watcher(client)
    old_door = _door("key-old", "door-old", "Old Door")
    original = {
        old_door.id: old_door,
        old_door.door_id: old_door,
    }
    watcher._door_map = dict(original)

    await watcher._load_door_map()

    assert watcher._door_map == original


async def test_unknown_door_forces_immediate_refresh() -> None:
    client = MagicMock()
    new_door = _door("key-new", "door-new", "New Door")
    client.get_doors = AsyncMock(return_value=[new_door])
    watcher = _watcher(client)
    watcher._door_map_loaded_at = time.monotonic()

    resolved = await watcher._resolve_door("door-new")

    assert resolved is new_door
    client.get_doors.assert_awaited_once()
