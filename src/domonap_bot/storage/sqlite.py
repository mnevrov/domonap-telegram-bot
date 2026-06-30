from pathlib import Path

import aiosqlite

from domonap_bot.storage.base import Storage


class SqliteStorage(Storage):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_store ("
            "  key   TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL"
            ")"
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def set(self, key: str, value: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self._conn.commit()

    async def get(self, key: str) -> str | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT value FROM kv_store WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def delete(self, key: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "DELETE FROM kv_store WHERE key = ?",
            (key,),
        )
        await self._conn.commit()
