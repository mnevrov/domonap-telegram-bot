from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path

_PRIVATE_FILE_MODE = 0o600


def _check_integrity(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        detail = row[0] if row else "no result"
        raise RuntimeError(f"SQLite integrity check failed: {detail}")


def _temporary_path(parent: Path, prefix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".db", dir=parent)
    os.close(fd)
    return Path(name)


def _harden_file(path: Path) -> None:
    if os.name == "posix":
        path.chmod(_PRIVATE_FILE_MODE)


def backup_database(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination.parent, f".{destination.name}.backup-")
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
            with sqlite3.connect(temporary) as backup_db:
                source_db.backup(backup_db)
                _check_integrity(backup_db)
        _harden_file(temporary)
        os.replace(temporary, destination)
        _harden_file(destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_database(backup: Path, destination: Path) -> None:
    backup = backup.resolve()
    destination = destination.resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"SQLite backup does not exist: {backup}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(destination.parent, f".{destination.name}.restore-")
    try:
        with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as backup_db:
            _check_integrity(backup_db)
            with sqlite3.connect(temporary) as restored_db:
                backup_db.backup(restored_db)
                _check_integrity(restored_db)
        _harden_file(temporary)
        os.replace(temporary, destination)
        _harden_file(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup or restore Domonap bot SQLite storage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="Create a consistent SQLite backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)

    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a verified backup; the bot must be stopped first",
    )
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("destination", type=Path)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "backup":
        backup_database(args.source, args.destination)
        print(f"Backup created: {args.destination}")
        return

    restore_database(args.backup, args.destination)
    print(f"Backup restored: {args.destination}")


if __name__ == "__main__":
    main()
