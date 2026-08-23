import sqlite3
from pathlib import Path

import pytest

from domonap_bot.storage_tools import backup_database, restore_database


def _create_db(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO kv_store (key, value) VALUES ('token', ?)", (value,))
        connection.commit()


def _read_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM kv_store WHERE key='token'").fetchone()
    assert row is not None
    return str(row[0])


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "storage.db"
    backup = tmp_path / "backups" / "storage.db"
    restored = tmp_path / "restored.db"
    _create_db(source, "secret-value")

    backup_database(source, backup)
    restore_database(backup, restored)

    assert _read_value(backup) == "secret-value"
    assert _read_value(restored) == "secret-value"


def test_corrupt_backup_does_not_replace_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "storage.db"
    corrupt = tmp_path / "corrupt.db"
    _create_db(destination, "keep-me")
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        restore_database(corrupt, destination)

    assert _read_value(destination) == "keep-me"


def test_backup_missing_source_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "missing.db", tmp_path / "backup.db")
