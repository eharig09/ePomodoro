from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from database.db import get_database_path


def _database_path(db_path: str | Path | None = None) -> Path:
    return (Path(db_path) if db_path is not None else get_database_path()).resolve()


def backup_directory(
    db_path: str | Path | None = None,
    backup_dir: str | Path | None = None,
) -> Path:
    source = _database_path(db_path)
    target = Path(backup_dir).resolve() if backup_dir else source.parent / "backups"
    target.mkdir(parents=True, exist_ok=True)
    return target


def create_database_backup(
    db_path: str | Path | None = None,
    *,
    backup_dir: str | Path | None = None,
    daily: bool = False,
    label: str = "manual",
) -> Path:
    source = _database_path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")
    target_dir = backup_directory(source, backup_dir)
    if daily:
        target = target_dir / f"focus-{date.today().isoformat()}-automatic.db"
        if target.exists():
            return target
    else:
        clean_label = "".join(
            character for character in label.lower() if character.isalnum() or character == "-"
        ) or "manual"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = target_dir / f"focus-{timestamp}-{clean_label}.db"

    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        target
    ) as target_connection:
        source_connection.backup(target_connection)
    return target


def list_database_backups(
    db_path: str | Path | None = None,
    *,
    backup_dir: str | Path | None = None,
) -> list[Path]:
    target_dir = backup_directory(db_path, backup_dir)
    return sorted(target_dir.glob("focus-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)


def database_integrity(db_path: str | Path | None = None) -> tuple[bool, str]:
    path = _database_path(db_path)
    try:
        with sqlite3.connect(path) as connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as exc:
        return False, str(exc)
    return result.casefold() == "ok", result


def export_database_json(db_path: str | Path | None = None) -> bytes:
    path = _database_path(db_path)
    exported: dict[str, list[dict[str, Any]]] = {}
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        for table in tables:
            safe_table = table.replace('"', '""')
            exported[table] = [
                dict(row)
                for row in connection.execute(f'SELECT * FROM "{safe_table}"').fetchall()
            ]
    payload = {
        "exported_at": datetime.now().astimezone().isoformat(),
        "database": path.name,
        "tables": exported,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def restore_database_backup(
    backup_path: str | Path,
    db_path: str | Path | None = None,
    *,
    backup_dir: str | Path | None = None,
) -> Path:
    destination = _database_path(db_path)
    allowed_dir = backup_directory(destination, backup_dir).resolve()
    source = Path(backup_path).resolve()
    if source.parent != allowed_dir or source.suffix.casefold() != ".db":
        raise ValueError("Restore source must be a database from the app backup folder")
    if not source.exists():
        raise FileNotFoundError("Selected backup no longer exists")
    valid, detail = database_integrity(source)
    if not valid:
        raise ValueError(f"Selected backup failed its integrity check: {detail}")

    safety_backup = create_database_backup(
        destination,
        backup_dir=allowed_dir,
        label="before-restore",
    )
    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        destination
    ) as destination_connection:
        source_connection.backup(destination_connection)
    return safety_backup
