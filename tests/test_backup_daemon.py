import sqlite3
from datetime import datetime, timedelta, timezone

from domonap_bot.backup_daemon import create_backup_once
from domonap_bot.storage_tools import restore_database


def _create_source(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES ('ok')")
        connection.commit()


def test_backup_daemon_rotates_and_restore_drill_succeeds(tmp_path) -> None:
    source = tmp_path / "storage.db"
    backup_dir = tmp_path / "backups"
    restored = tmp_path / "restored.db"
    _create_source(source)

    base = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    created = [
        create_backup_once(
            source,
            backup_dir,
            retention_count=2,
            now=base + timedelta(hours=offset),
        )
        for offset in (0, 1, 2)
    ]

    existing = sorted(backup_dir.glob("storage-*.db"))
    assert len(existing) == 2
    assert created[0] not in existing
    assert created[-1] in existing

    restore_database(created[-1], restored)
    with sqlite3.connect(restored) as connection:
        row = connection.execute("SELECT value FROM sample").fetchone()
    assert row == ("ok",)
