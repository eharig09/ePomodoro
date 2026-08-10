from datetime import date, datetime, timezone

from services.habit_service import (
    best_streak,
    checkin_dates_by_habit,
    current_streak,
    habit_from_todoist,
    match_completed_task_to_habit,
    matching_habits_for_task,
    recent_dates,
    record_task_completion,
    sync_completed_habit_history,
    task_link_from_todoist,
)
from database.db import (
    create_habit_definition,
    get_habit_daily_checkins,
    init_db,
)
from database.models import HabitDefinition
from services.todoist_service import TodoistTask


def recurring_task() -> TodoistTask:
    return TodoistTask(
        id="habit-1",
        content="Read",
        description="",
        project_id="personal",
        project_name="Personal",
        section_id=None,
        priority=2,
        labels=(),
        due_date="2026-08-10",
        due_datetime=None,
        url=None,
        due_string="every day",
        is_recurring=True,
    )


def test_recurring_todoist_task_becomes_habit_snapshot() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    habit = habit_from_todoist(recurring_task(), now=now)

    assert habit.todoist_task_id == "habit-1"
    assert habit.recurrence == "every day"
    assert habit.created_at == now


def test_current_streak_keeps_yesterdays_streak_until_today_is_done() -> None:
    today = date(2026, 8, 10)
    rows = [
        {"todoist_task_id": "habit-1", "completed_on": "2026-08-07"},
        {"todoist_task_id": "habit-1", "completed_on": "2026-08-08"},
        {"todoist_task_id": "habit-1", "completed_on": "2026-08-09"},
    ]
    grouped = checkin_dates_by_habit(rows)

    assert current_streak(grouped["habit-1"], today=today) == 3
    assert recent_dates(today=today, days=3) == [
        date(2026, 8, 8),
        date(2026, 8, 9),
        date(2026, 8, 10),
    ]


def test_current_streak_counts_only_scheduled_occurrences() -> None:
    completed = {
        date(2026, 8, 3),
        date(2026, 8, 5),
        date(2026, 8, 7),
    }

    assert current_streak(
        completed,
        today=date(2026, 8, 9),
        scheduled_weekdays=(0, 2, 4),
    ) == 3


def test_current_streak_breaks_on_missed_scheduled_day() -> None:
    completed = {
        date(2026, 8, 3),
        date(2026, 8, 5),
        date(2026, 8, 8),  # Off-day work does not repair missed Friday.
    }

    assert current_streak(
        completed,
        today=date(2026, 8, 10),
        scheduled_weekdays=(0, 2, 4),
    ) == 0


def test_best_streak_uses_scheduled_occurrences() -> None:
    completed = {
        date(2026, 7, 27),
        date(2026, 7, 29),
        date(2026, 7, 31),
        date(2026, 8, 5),  # Monday, August 3 was missed.
        date(2026, 8, 7),
    }

    assert best_streak(
        completed,
        today=date(2026, 8, 10),
        scheduled_weekdays=(0, 2, 4),
    ) == 3


def test_archived_recurring_occurrence_matches_tracked_habit_snapshot() -> None:
    tracked = habit_from_todoist(recurring_task())
    archived = TodoistTask(
        id="archived-occurrence-id",
        content=tracked.content,
        description="",
        project_id=tracked.project_id,
        project_name=tracked.project_name,
        section_id=None,
        priority=tracked.priority,
        labels=(),
        due_date="2026-08-09",
        due_datetime=None,
        url=None,
        due_string=tracked.recurrence,
        is_recurring=True,
        completed_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    matched = match_completed_task_to_habit(archived, [tracked])

    assert matched == tracked


def test_nonrecurring_task_with_same_name_is_not_imported_as_habit() -> None:
    tracked = habit_from_todoist(recurring_task())
    ordinary_task = TodoistTask(
        id="ordinary-task",
        content=tracked.content,
        description="",
        project_id=tracked.project_id,
        project_name=tracked.project_name,
        section_id=None,
        priority=1,
        labels=(),
        due_date="2026-08-09",
        due_datetime=None,
        url=None,
        completed_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )

    assert match_completed_task_to_habit(ordinary_task, [tracked]) is None


def test_one_task_can_match_multiple_generic_habits() -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    task = recurring_task()
    task = TodoistTask(
        **{
            field: getattr(task, field)
            for field in task.__dataclass_fields__
            if field not in {"labels"}
        },
        labels=("learning",),
    )
    label_habit = HabitDefinition(
        id="label-habit",
        name="Learn something",
        group_name="Growth",
        created_at=now,
        updated_at=now,
    )
    task_habit = HabitDefinition(
        id="task-habit",
        name="Read",
        group_name="Growth",
        created_at=now,
        updated_at=now,
    )

    matches = matching_habits_for_task(
        task,
        habits=[label_habit, task_habit],
        task_links=[task_link_from_todoist(task, habit_id=task_habit.id)],
        label_links={label_habit.id: {"learning"}},
    )

    assert {habit.id for habit in matches} == {label_habit.id, task_habit.id}


def test_shared_completion_recorder_is_idempotent_for_focus_and_sync(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    task = recurring_task()
    habit = create_habit_definition(
        "Read",
        task_links=[task_link_from_todoist(task)],
        db_path=db_path,
    )
    completed_at = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    focus_matches = record_task_completion(
        task,
        completed_at=completed_at,
        source="focus",
        db_path=db_path,
    )
    sync_matches = record_task_completion(
        task,
        completed_at=completed_at,
        source="todoist",
        db_path=db_path,
    )

    assert [matched.id for matched in focus_matches] == [habit.id]
    assert [matched.id for matched in sync_matches] == [habit.id]
    rows = get_habit_daily_checkins(db_path)
    assert len(rows) == 1
    assert rows[0]["source"] == "focus"


class CompletedHistoryService:
    def __init__(self, completed_task: TodoistTask) -> None:
        self.completed_task = completed_task

    def get_completed_tasks(self, *, since, until, project_names=None):
        assert since < until
        return [self.completed_task]

    def get_completed_task_events(self, *, since, until, project_names=None):
        assert since < until
        return []


def test_startup_history_sync_records_prelaunch_completion(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    task = recurring_task()
    completed_at = datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc)
    completed_task = TodoistTask(
        **{
            field: getattr(task, field)
            for field in task.__dataclass_fields__
            if field not in {"completed_at"}
        },
        completed_at=completed_at,
    )
    habit = create_habit_definition(
        "Read",
        task_links=[task_link_from_todoist(task)],
        db_path=db_path,
    )

    completed, match_count = sync_completed_habit_history(
        "test-token",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        service=CompletedHistoryService(completed_task),
        db_path=db_path,
    )

    assert completed == [completed_task]
    assert match_count == 1
    rows = get_habit_daily_checkins(db_path)
    assert len(rows) == 1
    assert rows[0]["habit_id"] == habit.id
    assert rows[0]["completed_at"] == completed_at.isoformat()
