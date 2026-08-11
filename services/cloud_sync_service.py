from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlencode
from uuid import uuid4

from database.db import connect
from services.cloud_account_service import CloudAccountError, CloudAccountService


ENTITY_TYPES = {
    "local_task",
    "focus_session",
    "habit",
    "habit_checkin",
    "reflection",
    "goal",
}


@dataclass(frozen=True, slots=True)
class LocalSyncEntity:
    entity_type: str
    entity_id: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SyncSummary:
    pushed: int
    pulled: int
    applied: int
    synced_at: datetime


def synchronize_cloud(
    account: CloudAccountService,
    db_path: str | Path | None = None,
) -> SyncSummary:
    device_id = _get_or_create_device_id(db_path)
    local = {
        (entity.entity_type, entity.entity_id): entity
        for entity in export_sync_entities(db_path)
    }
    shadow = _load_shadow(db_path)
    pending = _pending_records(local, shadow, device_id=device_id)
    pushed = len(pending)
    if pending:
        try:
            account.authorized_json(
                "POST",
                "/rest/v1/rpc/merge_sync_records",
                payload={"p_records": pending},
            )
        except CloudAccountError as exc:
            # Older projects may not have the goal entity migration yet. Keep
            # all existing sync data working and retry goals on the next sync.
            legacy_schema = "sync_records_entity_type_check" in str(exc)
            without_goals = [
                record for record in pending if record["entity_type"] != "goal"
            ]
            if not legacy_schema or len(without_goals) == len(pending):
                raise
            pushed = len(without_goals)
            if without_goals:
                account.authorized_json(
                    "POST",
                    "/rest/v1/rpc/merge_sync_records",
                    payload={"p_records": without_goals},
                )

    remote = _fetch_all_records(account)
    applied = apply_remote_records(remote, db_path)
    synced_at = datetime.now(timezone.utc)
    with connect(db_path) as connection, connection:
        connection.execute(
            """
            INSERT INTO cloud_sync_state (key, value) VALUES ('last_sync', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (synced_at.isoformat(),),
        )
    return SyncSummary(
        pushed=pushed,
        pulled=len(remote),
        applied=applied,
        synced_at=synced_at,
    )


def export_sync_entities(
    db_path: str | Path | None = None,
) -> list[LocalSyncEntity]:
    entities: list[LocalSyncEntity] = []
    with connect(db_path) as connection:
        for row in connection.execute(
            "SELECT * FROM local_focus_tasks ORDER BY id"
        ).fetchall():
            entities.append(
                LocalSyncEntity(
                    "local_task",
                    str(row["id"]),
                    {
                        "title": str(row["content"]),
                        "description": str(row["description"]),
                        "project": str(row["project_name"]),
                        "priority": int(row["priority"]),
                        "created_at": str(row["created_at"]),
                        "completed_at": (
                            str(row["completed_at"]) if row["completed_at"] else None
                        ),
                    },
                )
            )

        for row in connection.execute(
            "SELECT * FROM focus_sessions ORDER BY session_uuid"
        ).fetchall():
            entities.append(
                LocalSyncEntity(
                    "focus_session",
                    str(row["session_uuid"]),
                    {
                        "task_name": str(row["task_name"]),
                        "project_name": str(row["project_name"] or "Local"),
                        "todoist_task_id": str(row["todoist_task_id"]),
                        "project_id": (
                            str(row["project_id"]) if row["project_id"] else None
                        ),
                        "started_at": str(row["started_at"]),
                        "ended_at": str(row["ended_at"]),
                        "planned_minutes": int(row["planned_minutes"]),
                        "actual_seconds": int(row["actual_seconds"]),
                        "status": str(row["status"]),
                        "notes": str(row["notes"]),
                        "created_at": str(row["created_at"]),
                        "is_provisional": bool(row["is_provisional"]),
                    },
                )
            )

        icons = {
            str(row["group_name"]): str(row["emoji"])
            for row in connection.execute(
                "SELECT group_name, emoji FROM habit_group_settings"
            ).fetchall()
        }
        labels: dict[str, list[str]] = {}
        for row in connection.execute(
            "SELECT habit_id, label FROM habit_label_links ORDER BY label"
        ).fetchall():
            labels.setdefault(str(row["habit_id"]), []).append(str(row["label"]))
        links: dict[str, list[dict[str, object]]] = {}
        for row in connection.execute(
            "SELECT * FROM habit_task_links ORDER BY todoist_task_id"
        ).fetchall():
            links.setdefault(str(row["habit_id"]), []).append(
                {
                    "todoist_task_id": str(row["todoist_task_id"]),
                    "content": str(row["content"]),
                    "project_id": (
                        str(row["project_id"]) if row["project_id"] else None
                    ),
                    "project_name": str(row["project_name"]),
                    "recurrence": (
                        str(row["recurrence"]) if row["recurrence"] else None
                    ),
                    "priority": int(row["priority"]),
                }
            )
        for row in connection.execute(
            "SELECT * FROM habit_definitions ORDER BY id"
        ).fetchall():
            habit_id = str(row["id"])
            group = str(row["group_name"])
            entities.append(
                LocalSyncEntity(
                    "habit",
                    habit_id,
                    {
                        "name": str(row["name"]),
                        "group_name": group,
                        "emoji": icons.get(group, "✨"),
                        "weekdays": [
                            int(part)
                            for part in str(row["scheduled_weekdays"]).split(",")
                            if part.strip()
                        ],
                        "tracking_mode": (
                            "todoistLabel"
                            if labels.get(habit_id)
                            else "taskName"
                            if links.get(habit_id)
                            else "manual"
                        ),
                        "todoist_labels": labels.get(habit_id, []),
                        "task_links": links.get(habit_id, []),
                        "is_active": bool(row["is_active"]),
                        "created_at": str(row["created_at"]),
                        "updated_at": str(row["updated_at"]),
                    },
                )
            )

        for row in connection.execute(
            "SELECT * FROM habit_daily_checkins ORDER BY habit_id, completed_on"
        ).fetchall():
            habit_id = str(row["habit_id"])
            completed_on = str(row["completed_on"])
            entities.append(
                LocalSyncEntity(
                    "habit_checkin",
                    f"{habit_id}:{completed_on}",
                    {
                        "habit_id": habit_id,
                        "completed_on": completed_on,
                        "completed_at": str(row["completed_at"]),
                        "source": str(row["source"]),
                        "todoist_task_id": (
                            str(row["todoist_task_id"])
                            if row["todoist_task_id"]
                            else None
                        ),
                        "todoist_task_name": (
                            str(row["todoist_task_name"])
                            if row["todoist_task_name"]
                            else None
                        ),
                    },
                )
            )

        for row in connection.execute(
            "SELECT * FROM daily_reflections ORDER BY entry_date"
        ).fetchall():
            entry_date = str(row["entry_date"])
            entities.append(
                LocalSyncEntity(
                    "reflection",
                    entry_date,
                    {
                        "entry_date": entry_date,
                        "mood": int(row["mood"]),
                        "journal": str(row["journal"]),
                        "updated_at": str(row["updated_at"]),
                    },
                )
            )

        goal_links: dict[str, list[dict[str, str]]] = {}
        for row in connection.execute(
            "SELECT * FROM goal_links ORDER BY goal_id, entity_type, entity_id"
        ).fetchall():
            goal_links.setdefault(str(row["goal_id"]), []).append(
                {
                    "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "entity_name": str(row["entity_name"]),
                }
            )
        for row in connection.execute("SELECT * FROM goals ORDER BY id").fetchall():
            goal_id = str(row["id"])
            entities.append(
                LocalSyncEntity(
                    "goal",
                    goal_id,
                    {
                        "name": str(row["name"]),
                        "description": str(row["description"]),
                        "target_date": (
                            str(row["target_date"]) if row["target_date"] else None
                        ),
                        "status": str(row["status"]),
                        "created_at": str(row["created_at"]),
                        "updated_at": str(row["updated_at"]),
                        "links": goal_links.get(goal_id, []),
                    },
                )
            )
    return entities


def apply_remote_records(
    records: Iterable[Mapping[str, object]],
    db_path: str | Path | None = None,
) -> int:
    normalized = [_normalize_remote(record) for record in records]
    normalized = [record for record in normalized if record is not None]
    shadow = _load_shadow(db_path)
    changed = [
        record
        for record in normalized
        if not _shadow_matches_remote(shadow.get(_record_key(record)), record)
    ]
    if not changed:
        return 0

    delete_priority = {
        "habit_checkin": 0,
        "focus_session": 1,
        "local_task": 1,
        "reflection": 1,
        "goal": 2,
        "habit": 2,
    }
    upsert_priority = {
        "habit": 0,
        "local_task": 1,
        "focus_session": 1,
        "reflection": 1,
        "goal": 1,
        "habit_checkin": 2,
    }
    deletes = sorted(
        (record for record in changed if record["deleted_at"] is not None),
        key=lambda record: delete_priority[str(record["entity_type"])],
    )
    upserts = sorted(
        (record for record in changed if record["deleted_at"] is None),
        key=lambda record: upsert_priority[str(record["entity_type"])],
    )
    with connect(db_path) as connection, connection:
        for record in deletes:
            _delete_entity(connection, record)
            _save_shadow(connection, record)
        for record in upserts:
            _upsert_entity(connection, record)
            _save_shadow(connection, record)
    return len(changed)


def _fetch_all_records(account: CloudAccountService) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    page_size = 1000
    while True:
        query = urlencode(
            {
                "select": (
                    "entity_type,entity_id,payload,client_updated_at,device_id,"
                    "deleted_at,server_updated_at"
                ),
                "order": "server_updated_at.asc,entity_type.asc,entity_id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            }
        )
        response = account.authorized_json(
            "GET", f"/rest/v1/sync_records?{query}"
        )
        if not isinstance(response, list):
            raise ValueError("The cloud sync response was not a list.")
        page = [dict(item) for item in response if isinstance(item, dict)]
        records.extend(page)
        if len(page) < page_size:
            return records
        offset += page_size


def _pending_records(
    local: Mapping[tuple[str, str], LocalSyncEntity],
    shadow: Mapping[tuple[str, str], Mapping[str, object]],
    *,
    device_id: str,
) -> list[dict[str, object]]:
    now = datetime.now(timezone.utc).isoformat()
    pending: list[dict[str, object]] = []
    for key, entity in local.items():
        payload_json = _canonical_json(entity.payload)
        previous = shadow.get(key)
        if (
            previous is not None
            and previous.get("deleted_at") is None
            and previous.get("payload_json") == payload_json
        ):
            continue
        pending.append(
            {
                "entity_type": entity.entity_type,
                "entity_id": entity.entity_id,
                "payload": entity.payload,
                "client_updated_at": now,
                "device_id": device_id,
                "deleted_at": None,
            }
        )
    for key, previous in shadow.items():
        if key in local or previous.get("deleted_at") is not None:
            continue
        pending.append(
            {
                "entity_type": key[0],
                "entity_id": key[1],
                "payload": {},
                "client_updated_at": now,
                "device_id": device_id,
                "deleted_at": now,
            }
        )
    return pending


def _load_shadow(
    db_path: str | Path | None,
) -> dict[tuple[str, str], dict[str, object]]:
    with connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM cloud_sync_shadow").fetchall()
    return {
        (str(row["entity_type"]), str(row["entity_id"])): dict(row)
        for row in rows
    }


def _get_or_create_device_id(db_path: str | Path | None) -> str:
    with connect(db_path) as connection, connection:
        row = connection.execute(
            "SELECT value FROM cloud_sync_state WHERE key = 'device_id'"
        ).fetchone()
        if row is not None:
            return str(row["value"])
        device_id = str(uuid4())
        connection.execute(
            "INSERT INTO cloud_sync_state (key, value) VALUES ('device_id', ?)",
            (device_id,),
        )
        return device_id


def _normalize_remote(record: Mapping[str, object]) -> dict[str, object] | None:
    entity_type = str(record.get("entity_type") or "")
    entity_id = str(record.get("entity_id") or "")
    payload = record.get("payload")
    if entity_type not in ENTITY_TYPES or not entity_id or not isinstance(payload, dict):
        return None
    client_updated_at = _valid_timestamp(record.get("client_updated_at"))
    server_updated_at = _valid_timestamp(record.get("server_updated_at"))
    device_id = str(record.get("device_id") or "")
    raw_deleted_at = record.get("deleted_at")
    deleted_at = _valid_timestamp(raw_deleted_at) if raw_deleted_at is not None else None
    if not client_updated_at or not server_updated_at or not device_id:
        return None
    if raw_deleted_at is not None and deleted_at is None:
        return None
    return {
        "entity_type": entity_type,
        "entity_id": entity_id[:300],
        "payload": dict(payload),
        "client_updated_at": client_updated_at,
        "server_updated_at": server_updated_at,
        "device_id": device_id[:200],
        "deleted_at": deleted_at,
    }


def _valid_timestamp(value: object) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _record_key(record: Mapping[str, object]) -> tuple[str, str]:
    return str(record["entity_type"]), str(record["entity_id"])


def _shadow_matches_remote(
    previous: Mapping[str, object] | None,
    record: Mapping[str, object],
) -> bool:
    if previous is None:
        return False
    return (
        previous.get("payload_json") == _canonical_json(record["payload"])
        and previous.get("client_updated_at") == record.get("client_updated_at")
        and previous.get("device_id") == record.get("device_id")
        and previous.get("deleted_at") == record.get("deleted_at")
    )


def _save_shadow(connection, record: Mapping[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO cloud_sync_shadow (
            entity_type, entity_id, payload_json, client_updated_at,
            device_id, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
            payload_json = excluded.payload_json,
            client_updated_at = excluded.client_updated_at,
            device_id = excluded.device_id,
            deleted_at = excluded.deleted_at
        """,
        (
            record["entity_type"],
            record["entity_id"],
            _canonical_json(record["payload"]),
            record["client_updated_at"],
            record["device_id"],
            record["deleted_at"],
        ),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _delete_entity(connection, record: Mapping[str, object]) -> None:
    entity_type, entity_id = _record_key(record)
    if entity_type == "local_task":
        connection.execute("DELETE FROM local_focus_tasks WHERE id = ?", (entity_id,))
    elif entity_type == "focus_session":
        connection.execute(
            "DELETE FROM focus_sessions WHERE session_uuid = ?", (entity_id,)
        )
    elif entity_type == "habit":
        connection.execute("DELETE FROM habit_definitions WHERE id = ?", (entity_id,))
    elif entity_type == "habit_checkin":
        payload = record["payload"]
        habit_id, _, completed_on = entity_id.rpartition(":")
        if isinstance(payload, dict):
            habit_id = str(payload.get("habit_id") or habit_id)
            completed_on = str(payload.get("completed_on") or completed_on)
        connection.execute(
            "DELETE FROM habit_daily_checkins WHERE habit_id = ? AND completed_on = ?",
            (habit_id, completed_on),
        )
    elif entity_type == "reflection":
        connection.execute(
            "DELETE FROM daily_reflections WHERE entry_date = ?", (entity_id,)
        )
    elif entity_type == "goal":
        connection.execute("DELETE FROM goals WHERE id = ?", (entity_id,))


def _upsert_entity(connection, record: Mapping[str, object]) -> None:
    entity_type, entity_id = _record_key(record)
    payload = record["payload"]
    if not isinstance(payload, dict):
        return
    timestamp = str(record["client_updated_at"])
    if entity_type == "local_task":
        connection.execute(
            """
            INSERT INTO local_focus_tasks (
                id, content, description, project_name, priority,
                created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content = excluded.content,
                description = excluded.description,
                project_name = excluded.project_name,
                priority = excluded.priority,
                completed_at = excluded.completed_at
            """,
            (
                entity_id,
                _text(payload.get("title"), 300, "Untitled task"),
                _text(payload.get("description"), 1_000),
                _text(payload.get("project"), 120, "Local"),
                _priority(payload.get("priority")),
                _valid_timestamp(payload.get("created_at")) or timestamp,
                _valid_timestamp(payload.get("completed_at")),
            ),
        )
    elif entity_type == "focus_session":
        status = str(payload.get("status") or "continue")
        if status not in {"completed", "continue", "interrupted", "abandoned"}:
            status = "continue"
        connection.execute(
            """
            INSERT INTO focus_sessions (
                session_uuid, todoist_task_id, task_name, project_id,
                project_name, started_at, ended_at, planned_minutes,
                actual_seconds, status, notes, created_at, is_provisional
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                is_provisional = excluded.is_provisional
            """,
            (
                entity_id,
                _text(payload.get("todoist_task_id"), 200, f"local:{entity_id}"),
                _text(payload.get("task_name"), 300, "Focus session"),
                _optional_text(payload.get("project_id"), 200),
                _text(payload.get("project_name"), 120, "Local"),
                _valid_timestamp(payload.get("started_at")) or timestamp,
                _valid_timestamp(payload.get("ended_at")) or timestamp,
                _positive_int(payload.get("planned_minutes"), maximum=1_440),
                _nonnegative_int(payload.get("actual_seconds"), maximum=604_800),
                status,
                _text(payload.get("notes"), 5_000),
                _valid_timestamp(payload.get("created_at")) or timestamp,
                int(bool(payload.get("is_provisional", False))),
            ),
        )
    elif entity_type == "habit":
        _upsert_habit(connection, entity_id, payload, timestamp)
    elif entity_type == "habit_checkin":
        habit_id = _text(payload.get("habit_id"), 300)
        completed_on = _date_text(payload.get("completed_on"))
        if not habit_id or not completed_on:
            return
        exists = connection.execute(
            "SELECT 1 FROM habit_definitions WHERE id = ?", (habit_id,)
        ).fetchone()
        if exists is None:
            return
        source = str(payload.get("source") or "migration")
        if source not in {"habits", "focus", "todoist", "migration", "app"}:
            source = "migration"
        if source == "app":
            source = "habits"
        connection.execute(
            """
            INSERT INTO habit_daily_checkins (
                habit_id, completed_on, completed_at, source,
                todoist_task_id, todoist_task_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(habit_id, completed_on) DO UPDATE SET
                completed_at = excluded.completed_at,
                source = excluded.source,
                todoist_task_id = excluded.todoist_task_id,
                todoist_task_name = excluded.todoist_task_name
            """,
            (
                habit_id,
                completed_on,
                _valid_timestamp(payload.get("completed_at")) or timestamp,
                source,
                _optional_text(payload.get("todoist_task_id"), 200),
                _optional_text(payload.get("todoist_task_name"), 300),
            ),
        )
    elif entity_type == "reflection":
        entry_date = _date_text(payload.get("entry_date")) or _date_text(entity_id)
        if not entry_date:
            return
        mood = min(5, max(1, _nonnegative_int(payload.get("mood"), maximum=5)))
        connection.execute(
            """
            INSERT INTO daily_reflections (entry_date, mood, journal, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(entry_date) DO UPDATE SET
                mood = excluded.mood,
                journal = excluded.journal,
                updated_at = excluded.updated_at
            """,
            (
                entry_date,
                mood,
                _text(payload.get("journal"), 10_000),
                _valid_timestamp(payload.get("updated_at")) or timestamp,
            ),
        )
    elif entity_type == "goal":
        status = str(payload.get("status") or "active")
        if status not in {"active", "paused", "completed"}:
            status = "active"
        target_date = _date_text(payload.get("target_date"))
        connection.execute(
            """
            INSERT INTO goals (
                id, name, description, target_date, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                target_date = excluded.target_date,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                entity_id,
                _text(payload.get("name"), 300, "Goal"),
                _text(payload.get("description"), 5_000),
                target_date,
                status,
                _valid_timestamp(payload.get("created_at")) or timestamp,
                _valid_timestamp(payload.get("updated_at")) or timestamp,
            ),
        )
        connection.execute("DELETE FROM goal_links WHERE goal_id = ?", (entity_id,))
        links = payload.get("links")
        if isinstance(links, list):
            connection.executemany(
                """
                INSERT INTO goal_links (goal_id, entity_type, entity_id, entity_name)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        entity_id,
                        _text(link.get("entity_type"), 20),
                        _text(link.get("entity_id"), 300),
                        _text(link.get("entity_name"), 300, "Linked item"),
                    )
                    for link in links
                    if isinstance(link, dict)
                    and _text(link.get("entity_type"), 20) in {"task", "habit"}
                    and _text(link.get("entity_id"), 300)
                ],
            )


def _upsert_habit(connection, entity_id: str, payload: dict, timestamp: str) -> None:
    weekdays = payload.get("weekdays")
    if not isinstance(weekdays, list):
        weekdays = list(range(7))
    normalized_days = sorted(
        {int(value) for value in weekdays if str(value).isdigit() and 0 <= int(value) <= 6}
    ) or list(range(7))
    group_name = _text(payload.get("group_name"), 120, "Habits")
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
            entity_id,
            _text(payload.get("name"), 300, "Habit"),
            group_name,
            ",".join(str(day) for day in normalized_days),
            int(bool(payload.get("is_active", True))),
            _valid_timestamp(payload.get("created_at")) or timestamp,
            _valid_timestamp(payload.get("updated_at")) or timestamp,
        ),
    )
    connection.execute("DELETE FROM habit_label_links WHERE habit_id = ?", (entity_id,))
    labels = payload.get("todoist_labels")
    if not isinstance(labels, list):
        single = _text(payload.get("todoist_label"), 100)
        labels = [single] if single else []
    cleaned_labels = sorted({_text(label, 100).casefold() for label in labels if _text(label, 100)})
    connection.executemany(
        "INSERT INTO habit_label_links (habit_id, label) VALUES (?, ?)",
        [(entity_id, label) for label in cleaned_labels],
    )
    connection.execute("DELETE FROM habit_task_links WHERE habit_id = ?", (entity_id,))
    links = payload.get("task_links")
    if isinstance(links, list):
        connection.executemany(
            """
            INSERT INTO habit_task_links (
                habit_id, todoist_task_id, content, project_id,
                project_name, recurrence, priority
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    entity_id,
                    _text(link.get("todoist_task_id"), 200),
                    _text(link.get("content"), 300, "Todoist task"),
                    _optional_text(link.get("project_id"), 200),
                    _text(link.get("project_name"), 120, "Todoist"),
                    _optional_text(link.get("recurrence"), 300),
                    _priority(link.get("priority")),
                )
                for link in links
                if isinstance(link, dict) and _text(link.get("todoist_task_id"), 200)
            ],
        )
    connection.execute(
        """
        INSERT INTO habit_group_settings (group_name, emoji, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(group_name) DO UPDATE SET
            emoji = excluded.emoji,
            updated_at = excluded.updated_at
        """,
        (group_name, _text(payload.get("emoji"), 16, "✨"), timestamp),
    )


def _text(value: object, maximum: int, default: str = "") -> str:
    cleaned = str(value).strip() if value is not None else ""
    return (cleaned or default)[:maximum]


def _optional_text(value: object, maximum: int) -> str | None:
    cleaned = _text(value, maximum)
    return cleaned or None


def _priority(value: object) -> int:
    return min(4, max(1, _nonnegative_int(value, maximum=4) or 1))


def _positive_int(value: object, *, maximum: int) -> int:
    return max(1, _nonnegative_int(value, maximum=maximum))


def _nonnegative_int(value: object, *, maximum: int) -> int:
    try:
        return min(maximum, max(0, int(value)))
    except (TypeError, ValueError):
        return 0


def _date_text(value: object) -> str | None:
    try:
        return datetime.fromisoformat(str(value)).date().isoformat()
    except ValueError:
        return None
