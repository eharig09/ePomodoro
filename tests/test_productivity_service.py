from datetime import date, datetime, timezone

from database.models import DailyReflection, HabitDefinition, TaskPreference
from services.productivity_service import (
    build_focus_profile,
    calculate_weekly_metrics,
    recommend_tasks,
)
from services.todoist_service import TodoistTask


def task(task_id: str, *, priority: int, due_date: str | None = None) -> TodoistTask:
    return TodoistTask(
        id=task_id,
        content=f"Task {task_id}",
        description="",
        project_id="p1",
        project_name="Work",
        section_id=None,
        priority=priority,
        labels=(),
        due_date=due_date,
        due_datetime=None,
        url=None,
    )


def test_recommendations_balance_priority_energy_time_and_goals() -> None:
    timestamp = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    tasks = [
        task("deep", priority=4),
        task("quick", priority=2, due_date="2026-08-10"),
    ]
    preferences = {
        "deep": TaskPreference("deep", "Deep", "Work", "high", 90, timestamp),
        "quick": TaskPreference("quick", "Quick", "Work", "low", 20, timestamp),
    }

    ranked = recommend_tasks(
        tasks,
        preferences=preferences,
        current_energy="low",
        available_minutes=25,
        goal_task_ids={"quick"},
        today=date(2026, 8, 10),
    )

    assert ranked[0]["task"].id == "quick"
    assert "due today" in ranked[0]["reasons"]
    assert "supports a goal" in ranked[0]["reasons"]


def test_focus_profile_learns_duration_period_and_mood() -> None:
    sessions = [
        {
            "started_at": "2026-08-10T13:00:00+00:00",
            "actual_seconds": 1500,
            "planned_minutes": 25,
            "status": "completed",
            "is_provisional": 0,
        },
        {
            "started_at": "2026-08-10T14:00:00+00:00",
            "actual_seconds": 1800,
            "planned_minutes": 25,
            "status": "completed",
            "is_provisional": 0,
        },
    ]
    reflection = DailyReflection(
        date(2026, 8, 10),
        4,
        "Good focus",
        datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
    )

    profile = build_focus_profile(sessions, [reflection])

    assert profile["sample_size"] == 2
    assert profile["suggested_minutes"] in {25, 30}
    assert profile["mood_focus_minutes"][4] == 55.0


def test_weekly_metrics_respect_scheduled_habit_days() -> None:
    created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    habit = HabitDefinition(
        "habit-1",
        "Workout",
        "Health",
        created,
        created,
        scheduled_weekdays=(0, 2, 4),
    )
    metrics = calculate_weekly_metrics(
        [
            {
                "started_at": "2026-08-03T13:00:00+00:00",
                "actual_seconds": 1200,
                "planned_minutes": 25,
                "status": "completed",
                "project_name": "Health",
                "is_provisional": 0,
            }
        ],
        [habit],
        [
            {"habit_id": "habit-1", "completed_on": "2026-08-03"},
            {"habit_id": "habit-1", "completed_on": "2026-08-05"},
        ],
        week_start=date(2026, 8, 3),
    )

    assert metrics["habit_due"] == 3
    assert metrics["habit_done"] == 2
    assert metrics["focus_seconds"] == 1200
