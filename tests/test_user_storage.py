from pathlib import Path

import pytest

from domonap_bot.storage.sqlite import SqliteStorage


@pytest.fixture
async def storage(tmp_path: Path) -> SqliteStorage:
    s = SqliteStorage(tmp_path / "test_users.db")
    await s.initialize()
    return s


async def test_set_and_is_user_allowed(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    assert await storage.is_user_allowed(42) is True


async def test_not_allowed_by_default(storage: SqliteStorage) -> None:
    assert await storage.is_user_allowed(99) is False


async def test_set_user_admin(storage: SqliteStorage) -> None:
    await storage.set_user_admin(42)
    assert await storage.is_user_admin(42) is True
    assert await storage.is_user_admin(99) is False


async def test_list_allowed_users(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(1)
    await storage.set_user_allowed(2)
    assert sorted(await storage.list_allowed_users()) == [1, 2]


async def test_list_allowed_users_empty(storage: SqliteStorage) -> None:
    assert await storage.list_allowed_users() == []


async def test_remove_user(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    await storage.set_user_admin(42)
    await storage.remove_user(42)
    assert await storage.is_user_allowed(42) is False
    assert await storage.is_user_admin(42) is False


async def test_remove_user_does_not_affect_other_users(storage: SqliteStorage) -> None:
    await storage.set_user_allowed(42)
    await storage.set_user_allowed(7)
    await storage.remove_user(42)
    assert await storage.is_user_allowed(7) is True


async def test_user_profile_roundtrip_and_removal(storage: SqliteStorage) -> None:
    await storage.set_user_profile(42, first_name="Alice", username="alice")

    assert await storage.get_user_profile(42) == {
        "first_name": "Alice",
        "username": "alice",
    }

    await storage.remove_user(42)
    assert await storage.get_user_profile(42) == {}
