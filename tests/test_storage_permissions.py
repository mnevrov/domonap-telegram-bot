import os
import stat

import pytest

from domonap_bot.storage.sqlite import SqliteStorage

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")


async def test_new_storage_directory_and_database_are_private(tmp_path) -> None:
    db_path = tmp_path / "private" / "storage.db"
    storage = SqliteStorage(db_path)

    try:
        await storage.initialize()
        await storage.set("secret", "value")
        assert await storage.get("secret") == "value"

        assert stat.S_IMODE(db_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    finally:
        await storage.close()


async def test_existing_parent_is_preserved_but_database_is_hardened(tmp_path) -> None:
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    db_path = parent / "storage.db"
    db_path.touch(mode=0o644)
    db_path.chmod(0o644)

    storage = SqliteStorage(db_path)
    try:
        await storage.initialize()

        assert stat.S_IMODE(parent.stat().st_mode) == 0o755
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    finally:
        await storage.close()
