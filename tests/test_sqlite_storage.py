from pathlib import Path

import pytest

from domonap_bot.storage.sqlite import SqliteStorage


@pytest.fixture
async def storage(tmp_path: Path) -> SqliteStorage:
    s = SqliteStorage(tmp_path / "sub" / "storage.db")
    await s.initialize()
    return s


async def test_initialize_creates_db_file(tmp_path: Path) -> None:
    db_path = tmp_path / "sub" / "storage.db"
    assert not db_path.exists()

    s = SqliteStorage(db_path)
    await s.initialize()

    assert db_path.exists()
    await s.close()


async def test_set_get_roundtrip(storage: SqliteStorage) -> None:
    await storage.set("key1", "value1")
    assert await storage.get("key1") == "value1"


async def test_get_missing_key_returns_none(storage: SqliteStorage) -> None:
    assert await storage.get("missing") is None


async def test_set_overwrites_existing_key(storage: SqliteStorage) -> None:
    await storage.set("key1", "value1")
    await storage.set("key1", "value2")
    assert await storage.get("key1") == "value2"


async def test_delete_removes_key(storage: SqliteStorage) -> None:
    await storage.set("key1", "value1")
    await storage.delete("key1")
    assert await storage.get("key1") is None


async def test_delete_missing_key_is_noop(storage: SqliteStorage) -> None:
    await storage.delete("missing")


async def test_close_does_not_raise(storage: SqliteStorage) -> None:
    await storage.close()
