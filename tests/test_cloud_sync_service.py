from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from database.db import (
    connect,
    create_goal,
    create_local_focus_task,
    get_daily_reflection,
    get_daily_plan,
    get_daily_ritual,
    get_goal_links,
    get_goals,
    get_weekly_plan,
    get_weekly_review,
    init_db,
    mark_daily_startup_complete,
    save_daily_plan,
    save_daily_shutdown,
    save_goal_links,
    save_task_preferences,
    save_weekly_plan,
    save_weekly_review,
)
from database.models import DailyPlan, TaskPreference, WeeklyPlan, WeeklyReview
from services.cloud_sync_service import apply_remote_records, synchronize_cloud


def remote_record(entity_type: str, entity_id: str, payload: dict, *, deleted=False):
    timestamp = "2026-08-10T14:30:00+00:00"
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
        "client_updated_at": timestamp,
        "server_updated_at": timestamp,
        "device_id": "android-device",
        "deleted_at": timestamp if deleted else None,
    }


def test_remote_records_apply_and_tombstones_delete(tmp_path: Path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    records = [
        remote_record(
            "local_task",
            "mobile-task-1",
            {
                "title": "Pack gym bag",
                "description": "",
                "project": "Personal",
                "priority": 3,
                "created_at": "2026-08-10T12:00:00Z",
                "completed_at": None,
            },
        ),
        remote_record(
            "reflection",
            "2026-08-10",
            {
                "entry_date": "2026-08-10",
                "mood": 4,
                "journal": "A focused day",
                "updated_at": "2026-08-10T14:00:00Z",
            },
        ),
    ]

    assert apply_remote_records(records, db_path) == 2
    with connect(db_path) as connection:
        task = connection.execute(
            "SELECT * FROM local_focus_tasks WHERE id = 'mobile-task-1'"
        ).fetchone()
    assert task is not None and task["content"] == "Pack gym bag"
    assert get_daily_reflection(datetime(2026, 8, 10).date(), db_path).journal == "A focused day"

    assert apply_remote_records(
        [remote_record("local_task", "mobile-task-1", {}, deleted=True)], db_path
    ) == 1
    with connect(db_path) as connection:
        assert connection.execute(
            "SELECT 1 FROM local_focus_tasks WHERE id = 'mobile-task-1'"
        ).fetchone() is None


class FakeCloudAccount:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict] = {}
        self.posts: list[list[dict]] = []

    def authorized_json(self, method: str, path: str, *, payload=None, **_):
        if method == "POST":
            values = payload["p_records"]
            self.posts.append(values)
            for value in values:
                stored = dict(value)
                stored["server_updated_at"] = value["client_updated_at"]
                self.records[(value["entity_type"], value["entity_id"])] = stored
            return len(values)
        return list(self.records.values())


def test_sync_detects_local_changes_and_deletions(tmp_path: Path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    task = create_local_focus_task(
        "Draft outline", project_name="Work", priority=4, db_path=db_path
    )
    cloud = FakeCloudAccount()

    first = synchronize_cloud(cloud, db_path)
    assert first.pushed == 1
    assert cloud.posts[0][0]["payload"]["title"] == "Draft outline"

    with connect(db_path) as connection, connection:
        connection.execute("DELETE FROM local_focus_tasks WHERE id = ?", (task.id,))
    second = synchronize_cloud(cloud, db_path)

    assert second.pushed == 1
    assert cloud.posts[-1][0]["deleted_at"] is not None


def test_goals_and_links_round_trip_through_cloud_sync(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    init_db(source)
    init_db(target)
    goal = create_goal(
        "Finish the course",
        description="Complete the final module",
        db_path=source,
    )
    save_goal_links(
        goal.id,
        [("habit", "habit-1", "Study")],
        db_path=source,
    )
    cloud = FakeCloudAccount()

    assert synchronize_cloud(cloud, source).pushed == 1
    assert synchronize_cloud(cloud, target).applied == 1

    restored = get_goals(target)
    assert len(restored) == 1
    assert restored[0].name == "Finish the course"
    assert get_goal_links(target, goal_id=goal.id) == [
        {
            "goal_id": goal.id,
            "entity_type": "habit",
            "entity_id": "habit-1",
            "entity_name": "Study",
        }
    ]


def test_plans_rituals_and_reviews_round_trip_through_cloud_sync(
    tmp_path: Path,
) -> None:
    source = tmp_path / "planning-source.db"
    target = tmp_path / "planning-target.db"
    init_db(source)
    init_db(target)
    timestamp = datetime(2026, 8, 10, 14, 30, tzinfo=timezone.utc)
    plan_date = timestamp.date()
    save_task_preferences(
        [TaskPreference("task-1", "Write", "Work", "high", 45, timestamp)],
        source,
    )
    save_daily_plan(
        DailyPlan(plan_date, "high", 180, "17:30", "Write clearly", timestamp),
        [
            {
                "task_id": "task-1",
                "task_name": "Write",
                "project_name": "Work",
                "source": "todoist",
                "position": 0,
                "is_top_three": True,
            }
        ],
        source,
    )
    mark_daily_startup_complete(plan_date, completed_at=timestamp, db_path=source)
    save_daily_shutdown(
        plan_date,
        resolutions={"task-1": "continue"},
        wins="Started the draft",
        blockers="Meeting",
        tomorrow_first_task_id="task-1",
        completed_at=timestamp,
        db_path=source,
    )
    save_weekly_plan(
        WeeklyPlan(plan_date, "Finish the draft", "Protect mornings", timestamp),
        source,
    )
    save_weekly_review(
        WeeklyReview(
            plan_date,
            4,
            "Good progress",
            "Meetings",
            "Block mornings",
            timestamp,
        ),
        source,
    )
    cloud = FakeCloudAccount()

    first = synchronize_cloud(cloud, source)
    second = synchronize_cloud(cloud, target)

    assert first.pushed == 5
    assert second.applied == 5
    restored_plan, restored_items = get_daily_plan(plan_date, target)
    assert restored_plan is not None and restored_plan.intention == "Write clearly"
    assert restored_items[0]["task_name"] == "Write"
    assert get_daily_ritual(plan_date, target).wins == "Started the draft"
    assert get_weekly_plan(plan_date, target).intention == "Protect mornings"
    assert get_weekly_review(plan_date, target).rating == 4
