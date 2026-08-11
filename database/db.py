from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping
from uuid import uuid4

from database.migrations import apply_migrations
from database.models import (
    CalendarSource,
    DailyReflection,
    DailyPlan,
    DailyRitual,
    FocusSessionCreate,
    Goal,
    Habit,
    HabitDefinition,
    HabitTaskLink,
    LocalFocusTask,
    SESSION_STATUSES,
    TaskPreference,
    WeeklyPlan,
    WeeklyReview,
)
from services.datetime_service import local_timestamp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "focus.db"
ALL_WEEKDAYS = (0, 1, 2, 3, 4, 5, 6)


def _normalize_scheduled_weekdays(weekdays: Iterable[int]) -> tuple[int, ...]:
    normalized = tuple(sorted({int(weekday) for weekday in weekdays}))
    if not normalized or any(weekday not in ALL_WEEKDAYS for weekday in normalized):
        raise ValueError("Choose at least one scheduled weekday")
    return normalized


def _serialize_scheduled_weekdays(weekdays: Iterable[int]) -> str:
    return ",".join(str(weekday) for weekday in _normalize_scheduled_weekdays(weekdays))


def _deserialize_scheduled_weekdays(value: object) -> tuple[int, ...]:
    if value is None or not str(value).strip():
        return ALL_WEEKDAYS
    return _normalize_scheduled_weekdays(
        int(part) for part in str(value).split(",") if part.strip()
    )


def get_database_path() -> Path:
    configured = os.getenv("FOCUS_DB_PATH")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DB_PATH


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path) if db_path is not None else get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path | None = None) -> None:
    with connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        apply_migrations(connection)


def save_focus_session(
    session: FocusSessionCreate, db_path: str | Path | None = None
) -> bool:
    session.validate()
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO focus_sessions (
                session_uuid, todoist_task_id, task_name, project_id, project_name,
                started_at, ended_at, planned_minutes, actual_seconds, status,
                notes, created_at, is_provisional
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(session_uuid) DO UPDATE SET
                todoist_task_id = excluded.todoist_task_id,
                task_name = excluded.task_name,
                project_id = excluded.project_id,
                project_name = excluded.project_name,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                planned_minutes = excluded.planned_minutes,
                actual_seconds = excluded.actual_seconds,
                status = excluded.status,
                notes = excluded.notes,
                is_provisional = 0
            WHERE focus_sessions.is_provisional = 1
            """,
            (
                session.session_uuid,
                session.todoist_task_id,
                session.task_name,
                session.project_id,
                session.project_name,
                session.started_at.isoformat(),
                session.ended_at.isoformat(),
                session.planned_minutes,
                session.actual_seconds,
                session.status,
                session.notes.strip(),
                created_at,
            ),
        )
        return cursor.rowcount == 1


def checkpoint_focus_session(
    session: FocusSessionCreate, db_path: str | Path | None = None
) -> bool:
    """Insert or refresh an in-progress session as a provisional Continue row."""
    session.validate()
    if session.status != "continue":
        raise ValueError("Timer checkpoints must use Continue status")
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO focus_sessions (
                session_uuid, todoist_task_id, task_name, project_id, project_name,
                started_at, ended_at, planned_minutes, actual_seconds, status,
                notes, created_at, is_provisional
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'continue', ?, ?, 1)
            ON CONFLICT(session_uuid) DO UPDATE SET
                ended_at = excluded.ended_at,
                actual_seconds = excluded.actual_seconds,
                planned_minutes = excluded.planned_minutes
            WHERE focus_sessions.is_provisional = 1
            """,
            (
                session.session_uuid,
                session.todoist_task_id,
                session.task_name,
                session.project_id,
                session.project_name,
                session.started_at.isoformat(),
                session.ended_at.isoformat(),
                session.planned_minutes,
                session.actual_seconds,
                session.notes.strip(),
                created_at,
            ),
        )
        return cursor.rowcount == 1


def get_focus_sessions(
    db_path: str | Path | None = None, *, limit: int | None = None
) -> list[dict[str, object]]:
    query = "SELECT * FROM focus_sessions ORDER BY started_at DESC"
    parameters: tuple[object, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (max(1, int(limit)),)
    with connect(db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def update_focus_session(
    session_id: int,
    *,
    task_name: str,
    project_name: str,
    started_at: datetime,
    planned_minutes: int,
    actual_seconds: int,
    status: str,
    notes: str = "",
    db_path: str | Path | None = None,
) -> bool:
    clean_task = task_name.strip()
    clean_project = project_name.strip()
    clean_notes = notes.strip()
    if session_id <= 0:
        raise ValueError("Session ID must be positive")
    if not clean_task or len(clean_task) > 500:
        raise ValueError("Task name must be between 1 and 500 characters")
    if len(clean_project) > 120:
        raise ValueError("Project name must be 120 characters or fewer")
    if started_at.tzinfo is None:
        raise ValueError("Session start must include a timezone")
    if not 1 <= planned_minutes <= 1_440:
        raise ValueError("Planned minutes must be between 1 and 1,440")
    if not 0 <= actual_seconds <= 7 * 86_400:
        raise ValueError("Actual seconds must be between 0 and 604,800")
    if status not in SESSION_STATUSES:
        raise ValueError(f"Unsupported session status: {status}")
    if len(clean_notes) > 500:
        raise ValueError("Notes must be 500 characters or fewer")

    with connect(db_path) as connection, connection:
        existing = connection.execute(
            "SELECT started_at, ended_at FROM focus_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if existing is None:
            return False
        previous_start = datetime.fromisoformat(str(existing["started_at"]))
        previous_end = datetime.fromisoformat(str(existing["ended_at"]))
        wall_duration = max(timedelta(0), previous_end - previous_start)
        new_end = started_at + wall_duration
        cursor = connection.execute(
            """
            UPDATE focus_sessions
            SET task_name = ?, project_name = ?, started_at = ?, ended_at = ?,
                planned_minutes = ?, actual_seconds = ?, status = ?, notes = ?,
                is_provisional = 0
            WHERE id = ?
            """,
            (
                clean_task,
                clean_project or None,
                started_at.isoformat(),
                new_end.isoformat(),
                planned_minutes,
                actual_seconds,
                status,
                clean_notes,
                session_id,
            ),
        )
        return cursor.rowcount == 1


def delete_focus_session(
    session_id: int, db_path: str | Path | None = None
) -> bool:
    if session_id <= 0:
        raise ValueError("Session ID must be positive")
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM focus_sessions WHERE id = ?", (session_id,)
        )
        return cursor.rowcount == 1


def create_local_focus_task(
    content: str,
    *,
    description: str = "",
    project_name: str = "Local",
    priority: int = 1,
    db_path: str | Path | None = None,
) -> LocalFocusTask:
    clean_content = content.strip()
    clean_description = description.strip()
    clean_project = project_name.strip() or "Local"
    if not clean_content:
        raise ValueError("Task name is required")
    if len(clean_content) > 300:
        raise ValueError("Task name must be 300 characters or fewer")
    if len(clean_description) > 1_000:
        raise ValueError("Description must be 1,000 characters or fewer")
    if len(clean_project) > 120:
        raise ValueError("Project name must be 120 characters or fewer")
    if priority not in (1, 2, 3, 4):
        raise ValueError("Priority must be between 1 and 4")

    created_at = datetime.now(timezone.utc)
    task = LocalFocusTask(
        id=str(uuid4()),
        content=clean_content,
        description=clean_description,
        project_name=clean_project,
        priority=priority,
        created_at=created_at,
    )
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO local_focus_tasks (
                id, content, description, project_name, priority, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.content,
                task.description,
                task.project_name,
                task.priority,
                task.created_at.isoformat(),
            ),
        )
    return task


def get_active_local_focus_tasks(
    db_path: str | Path | None = None,
) -> list[LocalFocusTask]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, content, description, project_name, priority, created_at
            FROM local_focus_tasks
            WHERE completed_at IS NULL
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [
        LocalFocusTask(
            id=str(row["id"]),
            content=str(row["content"]),
            description=str(row["description"]),
            project_name=str(row["project_name"]),
            priority=int(row["priority"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
        for row in rows
    ]


def complete_local_focus_task(
    task_id: str, db_path: str | Path | None = None
) -> bool:
    completed_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE local_focus_tasks
            SET completed_at = ?
            WHERE id = ? AND completed_at IS NULL
            """,
            (completed_at, task_id),
        )
        return cursor.rowcount == 1


def set_tracked_habits(
    habits: Iterable[Habit],
    selected_task_ids: Iterable[str],
    db_path: str | Path | None = None,
) -> None:
    snapshots = {habit.todoist_task_id: habit for habit in habits}
    selected = {str(task_id) for task_id in selected_task_ids}
    unknown = selected.difference(snapshots)
    if unknown:
        raise ValueError("Selected habits must be recurring Todoist tasks")

    updated_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE habits SET is_active = 0, updated_at = ? WHERE is_active = 1",
            (updated_at,),
        )
        for task_id in selected:
            habit = snapshots[task_id]
            connection.execute(
                """
                INSERT INTO habits (
                    todoist_task_id, content, project_id, project_name, recurrence,
                    priority, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(todoist_task_id) DO UPDATE SET
                    content = excluded.content,
                    project_id = excluded.project_id,
                    project_name = excluded.project_name,
                    recurrence = excluded.recurrence,
                    priority = excluded.priority,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    habit.todoist_task_id,
                    habit.content,
                    habit.project_id,
                    habit.project_name,
                    habit.recurrence,
                    habit.priority,
                    habit.created_at.isoformat(),
                    updated_at,
                ),
            )


def upsert_tracked_habit(
    habit: Habit, db_path: str | Path | None = None
) -> None:
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO habits (
                todoist_task_id, content, project_id, project_name, recurrence,
                priority, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(todoist_task_id) DO UPDATE SET
                content = excluded.content,
                project_id = excluded.project_id,
                project_name = excluded.project_name,
                recurrence = excluded.recurrence,
                priority = excluded.priority,
                is_active = 1,
                updated_at = excluded.updated_at
            """,
            (
                habit.todoist_task_id,
                habit.content,
                habit.project_id,
                habit.project_name,
                habit.recurrence,
                habit.priority,
                habit.created_at.isoformat(),
                habit.updated_at.isoformat(),
            ),
        )


def get_habits(
    db_path: str | Path | None = None, *, active_only: bool = True
) -> list[Habit]:
    query = "SELECT * FROM habits"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY project_name COLLATE NOCASE, content COLLATE NOCASE"
    with connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [
        Habit(
            todoist_task_id=str(row["todoist_task_id"]),
            content=str(row["content"]),
            project_id=(str(row["project_id"]) if row["project_id"] else None),
            project_name=str(row["project_name"]),
            recurrence=str(row["recurrence"]),
            priority=int(row["priority"]),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    ]


def record_habit_checkin(
    todoist_task_id: str,
    completed_at: datetime,
    *,
    source: str,
    db_path: str | Path | None = None,
) -> bool:
    if completed_at.tzinfo is None:
        raise ValueError("Habit completion must include a timezone")
    if source not in {"app", "todoist"}:
        raise ValueError("Habit check-in source must be app or todoist")

    completed_on = local_timestamp(completed_at).date().isoformat()
    with connect(db_path) as connection, connection:
        exists = connection.execute(
            "SELECT 1 FROM habits WHERE todoist_task_id = ?",
            (str(todoist_task_id),),
        ).fetchone()
        if exists is None:
            return False
        cursor = connection.execute(
            """
            INSERT INTO habit_checkins (
                todoist_task_id, completed_on, completed_at, source
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(todoist_task_id, completed_on) DO UPDATE SET
                completed_at = excluded.completed_at,
                source = CASE
                    WHEN habit_checkins.source = 'app' THEN 'app'
                    ELSE excluded.source
                END
            """,
            (
                str(todoist_task_id),
                completed_on,
                completed_at.astimezone(timezone.utc).isoformat(),
                source,
            ),
        )
        return cursor.rowcount == 1


def get_habit_checkins(
    db_path: str | Path | None = None,
    *,
    since: date | None = None,
) -> list[dict[str, object]]:
    query = "SELECT * FROM habit_checkins"
    parameters: tuple[object, ...] = ()
    if since is not None:
        query += " WHERE completed_on >= ?"
        parameters = (since.isoformat(),)
    query += " ORDER BY completed_on DESC, completed_at DESC"
    with connect(db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def save_habit_definition(
    habit: HabitDefinition,
    task_links: Iterable[HabitTaskLink],
    labels: Iterable[str],
    db_path: str | Path | None = None,
) -> None:
    clean_name = habit.name.strip()
    clean_group = habit.group_name.strip() or "Habits"
    links = list(task_links)
    clean_labels = sorted(
        {label.strip().removeprefix("@").casefold() for label in labels if label.strip()}
    )
    if not clean_name or len(clean_name) > 300:
        raise ValueError("Habit name must be between 1 and 300 characters")
    if len(clean_group) > 120:
        raise ValueError("Habit group must be 120 characters or fewer")
    scheduled_weekdays = _serialize_scheduled_weekdays(habit.scheduled_weekdays)
    if any(link.habit_id != habit.id for link in links):
        raise ValueError("Habit task links must belong to the saved habit")
    if any(not 1 <= link.priority <= 4 for link in links):
        raise ValueError("Linked Todoist priority must be between 1 and 4")

    if habit.created_at.tzinfo is None or habit.updated_at.tzinfo is None:
        raise ValueError("Habit timestamps must include a timezone")
    updated_at = habit.updated_at
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO habit_definitions (
                id, name, group_name, scheduled_weekdays, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                group_name = excluded.group_name,
                scheduled_weekdays = excluded.scheduled_weekdays,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                habit.id,
                clean_name,
                clean_group,
                scheduled_weekdays,
                int(habit.is_active),
                habit.created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )
        connection.execute("DELETE FROM habit_task_links WHERE habit_id = ?", (habit.id,))
        connection.execute("DELETE FROM habit_label_links WHERE habit_id = ?", (habit.id,))
        connection.executemany(
            """
            INSERT INTO habit_task_links (
                habit_id, todoist_task_id, content, project_id, project_name,
                recurrence, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    link.habit_id,
                    link.todoist_task_id,
                    link.content,
                    link.project_id,
                    link.project_name,
                    link.recurrence,
                    link.priority,
                )
                for link in links
            ],
        )
        connection.executemany(
            "INSERT INTO habit_label_links (habit_id, label) VALUES (?, ?)",
            [(habit.id, label) for label in clean_labels],
        )


def create_habit_definition(
    name: str,
    *,
    group_name: str = "Habits",
    task_links: Iterable[HabitTaskLink] = (),
    labels: Iterable[str] = (),
    scheduled_weekdays: Iterable[int] = ALL_WEEKDAYS,
    db_path: str | Path | None = None,
) -> HabitDefinition:
    timestamp = datetime.now(timezone.utc)
    habit_id = str(uuid4())
    links = [
        HabitTaskLink(
            habit_id=habit_id,
            todoist_task_id=link.todoist_task_id,
            content=link.content,
            project_id=link.project_id,
            project_name=link.project_name,
            recurrence=link.recurrence,
            priority=link.priority,
        )
        for link in task_links
    ]
    habit = HabitDefinition(
        id=habit_id,
        name=name.strip(),
        group_name=group_name.strip() or "Habits",
        created_at=timestamp,
        updated_at=timestamp,
        scheduled_weekdays=_normalize_scheduled_weekdays(scheduled_weekdays),
    )
    save_habit_definition(habit, links, labels, db_path)
    return habit


def get_habit_definitions(
    db_path: str | Path | None = None, *, active_only: bool = True
) -> list[HabitDefinition]:
    query = "SELECT * FROM habit_definitions"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY group_name COLLATE NOCASE, name COLLATE NOCASE"
    with connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [
        HabitDefinition(
            id=str(row["id"]),
            name=str(row["name"]),
            group_name=str(row["group_name"]),
            scheduled_weekdays=_deserialize_scheduled_weekdays(
                row["scheduled_weekdays"]
            ),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    ]


def get_habit_task_links(
    db_path: str | Path | None = None, *, habit_id: str | None = None
) -> list[HabitTaskLink]:
    query = "SELECT * FROM habit_task_links"
    parameters: tuple[object, ...] = ()
    if habit_id is not None:
        query += " WHERE habit_id = ?"
        parameters = (habit_id,)
    query += " ORDER BY project_name COLLATE NOCASE, content COLLATE NOCASE"
    with connect(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [
        HabitTaskLink(
            habit_id=str(row["habit_id"]),
            todoist_task_id=str(row["todoist_task_id"]),
            content=str(row["content"]),
            project_id=(str(row["project_id"]) if row["project_id"] else None),
            project_name=str(row["project_name"]),
            recurrence=(str(row["recurrence"]) if row["recurrence"] else None),
            priority=int(row["priority"]),
        )
        for row in rows
    ]


def get_habit_label_links(
    db_path: str | Path | None = None, *, habit_id: str | None = None
) -> dict[str, set[str]]:
    query = "SELECT habit_id, label FROM habit_label_links"
    parameters: tuple[object, ...] = ()
    if habit_id is not None:
        query += " WHERE habit_id = ?"
        parameters = (habit_id,)
    with connect(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["habit_id"]), set()).add(str(row["label"]))
    return grouped


def set_habit_definition_active(
    habit_id: str,
    active: bool,
    db_path: str | Path | None = None,
) -> bool:
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE habit_definitions
            SET is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (int(active), datetime.now(timezone.utc).isoformat(), habit_id),
        )
        return cursor.rowcount == 1


def refresh_habit_task_link(
    link: HabitTaskLink,
    db_path: str | Path | None = None,
) -> int:
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE habit_task_links
            SET content = ?, project_id = ?, project_name = ?, recurrence = ?, priority = ?
            WHERE todoist_task_id = ?
            """,
            (
                link.content,
                link.project_id,
                link.project_name,
                link.recurrence,
                link.priority,
                link.todoist_task_id,
            ),
        )
        return cursor.rowcount


def record_habit_daily_checkin(
    habit_id: str,
    completed_at: datetime,
    *,
    source: str,
    todoist_task_id: str | None = None,
    todoist_task_name: str | None = None,
    db_path: str | Path | None = None,
) -> bool:
    if completed_at.tzinfo is None:
        raise ValueError("Habit completion must include a timezone")
    if source not in {"habits", "focus", "todoist", "migration"}:
        raise ValueError("Unsupported habit check-in source")
    completed_on = local_timestamp(completed_at).date().isoformat()
    with connect(db_path) as connection, connection:
        exists = connection.execute(
            "SELECT 1 FROM habit_definitions WHERE id = ? AND is_active = 1",
            (habit_id,),
        ).fetchone()
        if exists is None:
            return False
        cursor = connection.execute(
            """
            INSERT INTO habit_daily_checkins (
                habit_id, completed_on, completed_at, source,
                todoist_task_id, todoist_task_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(habit_id, completed_on) DO NOTHING
            """,
            (
                habit_id,
                completed_on,
                completed_at.astimezone(timezone.utc).isoformat(),
                source,
                todoist_task_id,
                todoist_task_name,
            ),
        )
        return cursor.rowcount == 1


def get_habit_daily_checkins(
    db_path: str | Path | None = None,
    *,
    since: date | None = None,
) -> list[dict[str, object]]:
    query = "SELECT * FROM habit_daily_checkins"
    parameters: tuple[object, ...] = ()
    if since is not None:
        query += " WHERE completed_on >= ?"
        parameters = (since.isoformat(),)
    query += " ORDER BY completed_on DESC, completed_at DESC"
    with connect(db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def get_habit_group_icons(
    db_path: str | Path | None = None,
) -> dict[str, str]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT group_name, emoji FROM habit_group_settings ORDER BY group_name"
        ).fetchall()
    return {str(row["group_name"]): str(row["emoji"]) for row in rows}


def save_habit_group_icons(
    icons: dict[str, str],
    db_path: str | Path | None = None,
) -> None:
    cleaned: list[tuple[str, str]] = []
    for group_name, emoji in icons.items():
        clean_group = str(group_name).strip()
        clean_emoji = str(emoji).strip() or "✨"
        if not clean_group or len(clean_group) > 120:
            raise ValueError("Habit group must be between 1 and 120 characters")
        if len(clean_emoji) > 16:
            raise ValueError("Group emoji must be 16 characters or fewer")
        cleaned.append((clean_group, clean_emoji))

    updated_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        connection.executemany(
            """
            INSERT INTO habit_group_settings (group_name, emoji, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(group_name) DO UPDATE SET
                emoji = excluded.emoji,
                updated_at = excluded.updated_at
            """,
            [(group_name, emoji, updated_at) for group_name, emoji in cleaned],
        )


def save_daily_reflection(
    entry_date: date,
    *,
    mood: int,
    journal: str = "",
    db_path: str | Path | None = None,
) -> DailyReflection:
    clean_journal = journal.strip()
    if mood not in range(1, 6):
        raise ValueError("Mood must be between 1 and 5")
    if len(clean_journal) > 10_000:
        raise ValueError("Journal entry must be 10,000 characters or fewer")
    updated_at = datetime.now(timezone.utc)
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO daily_reflections (entry_date, mood, journal, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(entry_date) DO UPDATE SET
                mood = excluded.mood,
                journal = excluded.journal,
                updated_at = excluded.updated_at
            """,
            (entry_date.isoformat(), mood, clean_journal, updated_at.isoformat()),
        )
    return DailyReflection(entry_date, mood, clean_journal, updated_at)


def get_daily_reflection(
    entry_date: date,
    db_path: str | Path | None = None,
) -> DailyReflection | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM daily_reflections WHERE entry_date = ?",
            (entry_date.isoformat(),),
        ).fetchone()
    if row is None:
        return None
    return DailyReflection(
        entry_date=date.fromisoformat(str(row["entry_date"])),
        mood=int(row["mood"]),
        journal=str(row["journal"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def get_daily_reflections(
    db_path: str | Path | None = None,
    *,
    since: date | None = None,
) -> list[DailyReflection]:
    query = "SELECT * FROM daily_reflections"
    parameters: tuple[object, ...] = ()
    if since is not None:
        query += " WHERE entry_date >= ?"
        parameters = (since.isoformat(),)
    query += " ORDER BY entry_date DESC"
    with connect(db_path) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [
        DailyReflection(
            entry_date=date.fromisoformat(str(row["entry_date"])),
            mood=int(row["mood"]),
            journal=str(row["journal"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    ]


def create_goal(
    name: str,
    *,
    description: str = "",
    target_date: date | None = None,
    db_path: str | Path | None = None,
) -> Goal:
    clean_name = name.strip()
    clean_description = description.strip()
    if not clean_name or len(clean_name) > 200:
        raise ValueError("Goal name must be between 1 and 200 characters")
    if len(clean_description) > 1_000:
        raise ValueError("Goal description must be 1,000 characters or fewer")
    timestamp = datetime.now(timezone.utc)
    goal = Goal(
        id=str(uuid4()),
        name=clean_name,
        description=clean_description,
        target_date=target_date,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO goals (
                id, name, description, target_date, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal.id,
                goal.name,
                goal.description,
                goal.target_date.isoformat() if goal.target_date else None,
                goal.status,
                goal.created_at.isoformat(),
                goal.updated_at.isoformat(),
            ),
        )
    return goal


def get_goals(
    db_path: str | Path | None = None,
    *,
    active_only: bool = False,
) -> list[Goal]:
    query = "SELECT * FROM goals"
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY status, target_date IS NULL, target_date, name COLLATE NOCASE"
    with connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [
        Goal(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            target_date=(
                date.fromisoformat(str(row["target_date"]))
                if row["target_date"]
                else None
            ),
            status=str(row["status"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    ]


def set_goal_status(
    goal_id: str,
    status: str,
    db_path: str | Path | None = None,
) -> bool:
    if status not in {"active", "paused", "completed"}:
        raise ValueError("Unsupported goal status")
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), goal_id),
        )
        return cursor.rowcount == 1


def delete_goal(goal_id: str, db_path: str | Path | None = None) -> bool:
    with connect(db_path) as connection, connection:
        cursor = connection.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        return cursor.rowcount == 1


def save_goal_links(
    goal_id: str,
    links: Iterable[tuple[str, str, str]],
    db_path: str | Path | None = None,
) -> None:
    normalized = [
        (str(entity_type), str(entity_id), str(entity_name).strip())
        for entity_type, entity_id, entity_name in links
    ]
    if any(entity_type not in {"task", "habit"} for entity_type, _, _ in normalized):
        raise ValueError("Goal links must reference a task or habit")
    if any(not entity_id or not entity_name for _, entity_id, entity_name in normalized):
        raise ValueError("Goal links require an ID and name")
    with connect(db_path) as connection, connection:
        exists = connection.execute(
            "SELECT 1 FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if exists is None:
            raise ValueError("Goal does not exist")
        connection.execute("DELETE FROM goal_links WHERE goal_id = ?", (goal_id,))
        connection.executemany(
            """
            INSERT INTO goal_links (goal_id, entity_type, entity_id, entity_name)
            VALUES (?, ?, ?, ?)
            """,
            [
                (goal_id, entity_type, entity_id, entity_name)
                for entity_type, entity_id, entity_name in normalized
            ],
        )


def get_goal_links(
    db_path: str | Path | None = None,
    *,
    goal_id: str | None = None,
) -> list[dict[str, str]]:
    query = "SELECT goal_id, entity_type, entity_id, entity_name FROM goal_links"
    parameters: tuple[object, ...] = ()
    if goal_id is not None:
        query += " WHERE goal_id = ?"
        parameters = (goal_id,)
    query += " ORDER BY entity_type, entity_name COLLATE NOCASE"
    with connect(db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def save_task_preferences(
    preferences: Iterable[TaskPreference],
    db_path: str | Path | None = None,
) -> None:
    rows = list(preferences)
    for preference in rows:
        if preference.energy_level not in {"low", "medium", "high"}:
            raise ValueError("Task energy must be low, medium, or high")
        if not 1 <= preference.estimated_minutes <= 1_440:
            raise ValueError("Task estimate must be between 1 and 1,440 minutes")
        if not preference.task_id or not preference.task_name.strip():
            raise ValueError("Task preferences require a task ID and name")
    with connect(db_path) as connection, connection:
        connection.executemany(
            """
            INSERT INTO task_preferences (
                task_id, task_name, project_name, energy_level,
                estimated_minutes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                task_name = excluded.task_name,
                project_name = excluded.project_name,
                energy_level = excluded.energy_level,
                estimated_minutes = excluded.estimated_minutes,
                updated_at = excluded.updated_at
            """,
            [
                (
                    preference.task_id,
                    preference.task_name.strip(),
                    preference.project_name.strip() or "Unknown project",
                    preference.energy_level,
                    preference.estimated_minutes,
                    preference.updated_at.isoformat(),
                )
                for preference in rows
            ],
        )


def get_task_preferences(
    db_path: str | Path | None = None,
) -> dict[str, TaskPreference]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM task_preferences").fetchall()
    return {
        str(row["task_id"]): TaskPreference(
            task_id=str(row["task_id"]),
            task_name=str(row["task_name"]),
            project_name=str(row["project_name"]),
            energy_level=str(row["energy_level"]),
            estimated_minutes=int(row["estimated_minutes"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    }


def save_daily_plan(
    plan: DailyPlan,
    items: Iterable[dict[str, object]],
    db_path: str | Path | None = None,
) -> None:
    if plan.energy_level not in {"low", "medium", "high"}:
        raise ValueError("Plan energy must be low, medium, or high")
    if not 1 <= plan.available_minutes <= 1_440:
        raise ValueError("Available minutes must be between 1 and 1,440")
    if len(plan.intention.strip()) > 500:
        raise ValueError("Daily intention must be 500 characters or fewer")
    item_rows = list(items)
    top_count = sum(bool(item.get("is_top_three")) for item in item_rows)
    if top_count > 3:
        raise ValueError("Choose no more than three top tasks")
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO daily_plans (
                plan_date, energy_level, available_minutes,
                shutdown_time, intention, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_date) DO UPDATE SET
                energy_level = excluded.energy_level,
                available_minutes = excluded.available_minutes,
                shutdown_time = excluded.shutdown_time,
                intention = excluded.intention,
                updated_at = excluded.updated_at
            """,
            (
                plan.plan_date.isoformat(),
                plan.energy_level,
                plan.available_minutes,
                plan.shutdown_time,
                plan.intention.strip(),
                plan.updated_at.isoformat(),
            ),
        )
        connection.execute(
            "DELETE FROM daily_plan_items WHERE plan_date = ?",
            (plan.plan_date.isoformat(),),
        )
        connection.executemany(
            """
            INSERT INTO daily_plan_items (
                plan_date, task_id, task_name, project_name, source,
                position, is_top_three, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan.plan_date.isoformat(),
                    str(item["task_id"]),
                    str(item["task_name"]),
                    str(item.get("project_name") or "Unknown project"),
                    str(item.get("source") or "todoist"),
                    int(item.get("position", index)),
                    int(bool(item.get("is_top_three"))),
                    str(item.get("status") or "planned"),
                )
                for index, item in enumerate(item_rows)
            ],
        )


def get_daily_plan(
    plan_date: date,
    db_path: str | Path | None = None,
) -> tuple[DailyPlan | None, list[dict[str, object]]]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM daily_plans WHERE plan_date = ?",
            (plan_date.isoformat(),),
        ).fetchone()
        items = [
            dict(item)
            for item in connection.execute(
                """
                SELECT * FROM daily_plan_items
                WHERE plan_date = ? ORDER BY position, task_name COLLATE NOCASE
                """,
                (plan_date.isoformat(),),
            ).fetchall()
        ]
    if row is None:
        return None, items
    return (
        DailyPlan(
            plan_date=date.fromisoformat(str(row["plan_date"])),
            energy_level=str(row["energy_level"]),
            available_minutes=int(row["available_minutes"]),
            shutdown_time=str(row["shutdown_time"]),
            intention=str(row["intention"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        ),
        items,
    )


def set_daily_plan_item_status(
    plan_date: date,
    task_id: str,
    status: str,
    db_path: str | Path | None = None,
) -> bool:
    if status not in {"planned", "completed", "deferred"}:
        raise ValueError("Unsupported plan item status")
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE daily_plan_items SET status = ?
            WHERE plan_date = ? AND task_id = ?
            """,
            (status, plan_date.isoformat(), task_id),
        )
        return cursor.rowcount == 1


def save_calendar_source(
    source: CalendarSource,
    ics_data: str,
    db_path: str | Path | None = None,
) -> None:
    source_id = source.id.strip()
    name = source.name.strip()
    provider = source.provider.strip().lower()
    if not source_id or len(source_id) > 100:
        raise ValueError("Calendar source ID is invalid")
    if not name or len(name) > 120:
        raise ValueError("Calendar name must be between 1 and 120 characters")
    if provider not in {"google", "outlook", "ics"}:
        raise ValueError("Unsupported calendar provider")
    if source.event_count < 0:
        raise ValueError("Calendar event count cannot be negative")
    if not ics_data.strip() or len(ics_data.encode("utf-8")) > 5_000_000:
        raise ValueError("Calendar data must be a valid file under 5 MB")
    if "BEGIN:VCALENDAR" not in ics_data[:1_000].upper():
        raise ValueError("Calendar data is not an iCalendar file")
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO calendar_sources (
                id, name, provider, ics_data, event_count,
                last_refreshed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                provider = excluded.provider,
                ics_data = excluded.ics_data,
                event_count = excluded.event_count,
                last_refreshed_at = excluded.last_refreshed_at,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                name,
                provider,
                ics_data,
                source.event_count,
                source.last_refreshed_at.isoformat(),
                source.created_at.isoformat(),
                source.updated_at.isoformat(),
            ),
        )


def get_calendar_sources(
    db_path: str | Path | None = None,
) -> list[CalendarSource]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, provider, event_count, last_refreshed_at,
                   created_at, updated_at
            FROM calendar_sources
            ORDER BY name COLLATE NOCASE, id
            """
        ).fetchall()
    return [
        CalendarSource(
            id=str(row["id"]),
            name=str(row["name"]),
            provider=str(row["provider"]),
            event_count=int(row["event_count"]),
            last_refreshed_at=datetime.fromisoformat(
                str(row["last_refreshed_at"])
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
        for row in rows
    ]


def get_calendar_source_data(
    source_id: str,
    db_path: str | Path | None = None,
) -> str | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT ics_data FROM calendar_sources WHERE id = ?",
            (source_id.strip(),),
        ).fetchone()
    return str(row["ics_data"]) if row else None


def delete_calendar_source(
    source_id: str,
    db_path: str | Path | None = None,
) -> bool:
    with connect(db_path) as connection, connection:
        cursor = connection.execute(
            "DELETE FROM calendar_sources WHERE id = ?",
            (source_id.strip(),),
        )
        return cursor.rowcount == 1


def get_daily_ritual(
    ritual_date: date,
    db_path: str | Path | None = None,
) -> DailyRitual | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM daily_rituals WHERE ritual_date = ?",
            (ritual_date.isoformat(),),
        ).fetchone()
    if row is None:
        return None
    return DailyRitual(
        ritual_date=date.fromisoformat(str(row["ritual_date"])),
        startup_completed_at=(
            datetime.fromisoformat(str(row["startup_completed_at"]))
            if row["startup_completed_at"]
            else None
        ),
        shutdown_completed_at=(
            datetime.fromisoformat(str(row["shutdown_completed_at"]))
            if row["shutdown_completed_at"]
            else None
        ),
        wins=str(row["wins"]),
        blockers=str(row["blockers"]),
        tomorrow_first_task_id=(
            str(row["tomorrow_first_task_id"])
            if row["tomorrow_first_task_id"]
            else None
        ),
        tomorrow_first_task_name=str(row["tomorrow_first_task_name"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def mark_daily_startup_complete(
    ritual_date: date,
    *,
    completed_at: datetime | None = None,
    db_path: str | Path | None = None,
) -> DailyRitual:
    timestamp = completed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Startup completion time must include a timezone")
    value = timestamp.astimezone(timezone.utc).isoformat()
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO daily_rituals (
                ritual_date, startup_completed_at, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(ritual_date) DO UPDATE SET
                startup_completed_at = COALESCE(
                    daily_rituals.startup_completed_at,
                    excluded.startup_completed_at
                ),
                updated_at = excluded.updated_at
            """,
            (ritual_date.isoformat(), value, value),
        )
    ritual = get_daily_ritual(ritual_date, db_path)
    if ritual is None:  # pragma: no cover - guarded by the upsert above
        raise RuntimeError("Daily startup could not be saved")
    return ritual


def save_daily_shutdown(
    ritual_date: date,
    *,
    resolutions: Mapping[str, str],
    wins: str = "",
    blockers: str = "",
    tomorrow_first_task_id: str | None = None,
    completed_at: datetime | None = None,
    db_path: str | Path | None = None,
) -> DailyRitual:
    allowed_resolutions = {"completed", "continue", "deferred"}
    if any(value not in allowed_resolutions for value in resolutions.values()):
        raise ValueError("Unsupported shutdown resolution")
    clean_wins = wins.strip()
    clean_blockers = blockers.strip()
    if len(clean_wins) > 5_000 or len(clean_blockers) > 5_000:
        raise ValueError("Daily shutdown fields must be 5,000 characters or fewer")
    timestamp = completed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Shutdown completion time must include a timezone")
    timestamp_text = timestamp.astimezone(timezone.utc).isoformat()
    date_text = ritual_date.isoformat()
    tomorrow = ritual_date + timedelta(days=1)

    with connect(db_path) as connection, connection:
        existing_ritual = connection.execute(
            "SELECT * FROM daily_rituals WHERE ritual_date = ?",
            (date_text,),
        ).fetchone()
        current_items = {
            str(row["task_id"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM daily_plan_items WHERE plan_date = ?",
                (date_text,),
            ).fetchall()
        }
        unfinished_ids = {
            task_id
            for task_id, item in current_items.items()
            if str(item["status"]) == "planned"
        }
        if set(resolutions) != unfinished_ids:
            raise ValueError("Resolve every unfinished planned task before shutdown")

        carry_ids = [
            task_id
            for task_id, resolution in resolutions.items()
            if resolution == "continue"
        ]
        preserve_first_task = bool(
            not unfinished_ids
            and existing_ritual
            and existing_ritual["shutdown_completed_at"]
            and tomorrow_first_task_id is None
        )
        if preserve_first_task:
            tomorrow_first_task_id = (
                str(existing_ritual["tomorrow_first_task_id"])
                if existing_ritual["tomorrow_first_task_id"]
                else None
            )
        if (
            tomorrow_first_task_id
            and tomorrow_first_task_id not in carry_ids
            and not preserve_first_task
        ):
            raise ValueError("Tomorrow's first task must be continued")

        for task_id, resolution in resolutions.items():
            status = "completed" if resolution == "completed" else "deferred"
            connection.execute(
                """
                UPDATE daily_plan_items SET status = ?
                WHERE plan_date = ? AND task_id = ?
                """,
                (status, date_text, task_id),
            )

        first_task_name = (
            str(existing_ritual["tomorrow_first_task_name"])
            if preserve_first_task
            else ""
        )
        if carry_ids:
            current_plan = connection.execute(
                "SELECT * FROM daily_plans WHERE plan_date = ?",
                (date_text,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO daily_plans (
                    plan_date, energy_level, available_minutes,
                    shutdown_time, intention, updated_at
                ) VALUES (?, ?, ?, ?, '', ?)
                ON CONFLICT(plan_date) DO NOTHING
                """,
                (
                    tomorrow.isoformat(),
                    str(current_plan["energy_level"]) if current_plan else "medium",
                    int(current_plan["available_minutes"]) if current_plan else 240,
                    str(current_plan["shutdown_time"]) if current_plan else "17:00",
                    timestamp_text,
                ),
            )
            if tomorrow_first_task_id:
                connection.execute(
                    """
                    UPDATE daily_plan_items SET position = position + 1
                    WHERE plan_date = ?
                    """,
                    (tomorrow.isoformat(),),
                )
            max_position_row = connection.execute(
                """
                SELECT COALESCE(MAX(position), -1) AS max_position
                FROM daily_plan_items WHERE plan_date = ?
                """,
                (tomorrow.isoformat(),),
            ).fetchone()
            next_position = int(max_position_row["max_position"]) + 1
            ordered_carry = sorted(
                carry_ids,
                key=lambda task_id: (
                    task_id != tomorrow_first_task_id,
                    int(current_items[task_id]["position"]),
                ),
            )
            for offset, task_id in enumerate(ordered_carry):
                item = current_items[task_id]
                position = 0 if task_id == tomorrow_first_task_id else next_position + offset
                connection.execute(
                    """
                    INSERT INTO daily_plan_items (
                        plan_date, task_id, task_name, project_name, source,
                        position, is_top_three, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 'planned')
                    ON CONFLICT(plan_date, task_id) DO UPDATE SET
                        task_name = excluded.task_name,
                        project_name = excluded.project_name,
                        source = excluded.source,
                        position = excluded.position,
                        status = 'planned'
                    WHERE daily_plan_items.status != 'completed'
                    """,
                    (
                        tomorrow.isoformat(),
                        task_id,
                        str(item["task_name"]),
                        str(item["project_name"]),
                        str(item["source"]),
                        position,
                    ),
                )
            if tomorrow_first_task_id:
                first_task_name = str(
                    current_items[tomorrow_first_task_id]["task_name"]
                )

        startup_completed_at = (
            str(existing_ritual["startup_completed_at"])
            if existing_ritual and existing_ritual["startup_completed_at"]
            else None
        )
        connection.execute(
            """
            INSERT INTO daily_rituals (
                ritual_date, startup_completed_at, shutdown_completed_at,
                wins, blockers, tomorrow_first_task_id,
                tomorrow_first_task_name, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ritual_date) DO UPDATE SET
                shutdown_completed_at = excluded.shutdown_completed_at,
                wins = excluded.wins,
                blockers = excluded.blockers,
                tomorrow_first_task_id = excluded.tomorrow_first_task_id,
                tomorrow_first_task_name = excluded.tomorrow_first_task_name,
                updated_at = excluded.updated_at
            """,
            (
                date_text,
                startup_completed_at,
                timestamp_text,
                clean_wins,
                clean_blockers,
                tomorrow_first_task_id,
                first_task_name,
                timestamp_text,
            ),
        )

    ritual = get_daily_ritual(ritual_date, db_path)
    if ritual is None:  # pragma: no cover - guarded by the upsert above
        raise RuntimeError("Daily shutdown could not be saved")
    return ritual


def save_weekly_plan(
    plan: WeeklyPlan,
    db_path: str | Path | None = None,
) -> None:
    if plan.week_start.weekday() != 0:
        raise ValueError("Weekly plans must start on Monday")
    objective_lines = [
        line.strip() for line in plan.objectives.splitlines() if line.strip()
    ]
    if not 1 <= len(objective_lines) <= 5:
        raise ValueError("Choose between one and five weekly objectives")
    objectives = "\n".join(objective_lines)
    intention = plan.intention.strip()
    if len(objectives) > 5_000 or len(intention) > 500:
        raise ValueError("Weekly plan text is too long")
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO weekly_plans (
                week_start, objectives, intention, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                objectives = excluded.objectives,
                intention = excluded.intention,
                updated_at = excluded.updated_at
            """,
            (
                plan.week_start.isoformat(),
                objectives,
                intention,
                plan.updated_at.isoformat(),
            ),
        )


def get_weekly_plan(
    week_start: date,
    db_path: str | Path | None = None,
) -> WeeklyPlan | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM weekly_plans WHERE week_start = ?",
            (week_start.isoformat(),),
        ).fetchone()
    if row is None:
        return None
    return WeeklyPlan(
        week_start=date.fromisoformat(str(row["week_start"])),
        objectives=str(row["objectives"]),
        intention=str(row["intention"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def save_weekly_review(
    review: WeeklyReview,
    db_path: str | Path | None = None,
) -> None:
    if review.week_start.weekday() != 0:
        raise ValueError("Weekly reviews must start on Monday")
    if review.rating not in range(1, 6):
        raise ValueError("Weekly rating must be between 1 and 5")
    if any(len(value.strip()) > 2_000 for value in (review.wins, review.blockers, review.adjustments)):
        raise ValueError("Weekly review fields must be 2,000 characters or fewer")
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO weekly_reviews (
                week_start, rating, wins, blockers, adjustments, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                rating = excluded.rating,
                wins = excluded.wins,
                blockers = excluded.blockers,
                adjustments = excluded.adjustments,
                updated_at = excluded.updated_at
            """,
            (
                review.week_start.isoformat(),
                review.rating,
                review.wins.strip(),
                review.blockers.strip(),
                review.adjustments.strip(),
                review.updated_at.isoformat(),
            ),
        )


def get_weekly_review(
    week_start: date,
    db_path: str | Path | None = None,
) -> WeeklyReview | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM weekly_reviews WHERE week_start = ?",
            (week_start.isoformat(),),
        ).fetchone()
    if row is None:
        return None
    return WeeklyReview(
        week_start=date.fromisoformat(str(row["week_start"])),
        rating=int(row["rating"]),
        wins=str(row["wins"]),
        blockers=str(row["blockers"]),
        adjustments=str(row["adjustments"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def record_sync_run(
    sync_type: str,
    *,
    status: str,
    item_count: int = 0,
    matched_count: int = 0,
    message: str = "",
    started_at: datetime | None = None,
    db_path: str | Path | None = None,
) -> None:
    if status not in {"success", "error"}:
        raise ValueError("Sync status must be success or error")
    timestamp = started_at or datetime.now(timezone.utc)
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO sync_runs (
                sync_type, started_at, status, item_count, matched_count, message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sync_type.strip() or "todoist",
                timestamp.astimezone(timezone.utc).isoformat(),
                status,
                max(0, int(item_count)),
                max(0, int(matched_count)),
                message.strip()[:1_000],
            ),
        )


def get_sync_runs(
    db_path: str | Path | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_app_setting(
    key: str,
    default: str | None = None,
    db_path: str | Path | None = None,
) -> str | None:
    clean_key = key.strip()
    if not clean_key:
        raise ValueError("Setting key is required")
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (clean_key,)
        ).fetchone()
    return str(row["value"]) if row is not None else default


def set_app_setting(
    key: str,
    value: str,
    db_path: str | Path | None = None,
) -> None:
    clean_key = key.strip()
    if not clean_key:
        raise ValueError("Setting key is required")
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (clean_key, str(value), datetime.now(timezone.utc).isoformat()),
        )
