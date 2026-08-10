import json

from database.db import create_local_focus_task, get_active_local_focus_tasks, init_db
from services.health_service import (
    create_database_backup,
    database_integrity,
    export_database_json,
    list_database_backups,
    restore_database_backup,
)


def test_backup_export_integrity_and_restore(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    backup_dir = tmp_path / "backups"
    init_db(db_path)
    create_local_focus_task("Keep me", db_path=db_path)

    backup = create_database_backup(db_path, backup_dir=backup_dir)
    create_local_focus_task("Remove after restore", db_path=db_path)
    assert len(get_active_local_focus_tasks(db_path)) == 2
    assert list_database_backups(db_path, backup_dir=backup_dir) == [backup]
    assert database_integrity(db_path) == (True, "ok")

    exported = json.loads(export_database_json(db_path))
    assert "focus_sessions" in exported["tables"]
    assert len(exported["tables"]["local_focus_tasks"]) == 2

    safety_backup = restore_database_backup(
        backup,
        db_path,
        backup_dir=backup_dir,
    )
    assert safety_backup.exists()
    assert [task.content for task in get_active_local_focus_tasks(db_path)] == ["Keep me"]
