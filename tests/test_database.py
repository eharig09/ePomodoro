from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from database.db import (
    checkpoint_focus_session,
    complete_local_focus_task,
    create_goal,
    create_habit_definition,
    create_local_focus_task,
    delete_focus_session,
    get_active_local_focus_tasks,
    get_app_setting,
    get_daily_reflection,
    get_daily_reflections,
    get_focus_sessions,
    get_daily_plan,
    get_goal_links,
    get_goals,
    get_habit_checkins,
    get_habit_daily_checkins,
    get_habit_definitions,
    get_habit_group_icons,
    get_habit_label_links,
    get_habit_task_links,
    get_habits,
    get_sync_runs,
    get_task_preferences,
    get_weekly_review,
    init_db,
    record_habit_checkin,
    record_habit_daily_checkin,
    save_focus_session,
    save_daily_plan,
    save_daily_reflection,
    save_habit_group_icons,
    save_goal_links,
    save_task_preferences,
    save_weekly_review,
    record_sync_run,
    set_daily_plan_item_status,
    set_app_setting,
    set_goal_status,
    set_tracked_habits,
    set_habit_definition_active,
    update_focus_session,
)
from database.models import (
    DailyPlan,
    FocusSessionCreate,
    Habit,
    HabitTaskLink,
    TaskPreference,
    WeeklyReview,
)


def make_session(session_uuid: str = "session-1") -> FocusSessionCreate:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    return FocusSessionCreate(
        session_uuid=session_uuid,
        todoist_task_id="123",
        task_name="Write the report",
        project_id="42",
        project_name="Work",
        started_at=started,
        ended_at=started + timedelta(minutes=20),
        planned_minutes=25,
        actual_seconds=1200,
        status="continue",
        notes="Drafted two sections",
    )


def test_session_write_and_duplicate_prevention(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)

    assert save_focus_session(make_session(), db_path) is True
    assert save_focus_session(make_session(), db_path) is False

    rows = get_focus_sessions(db_path)
    assert len(rows) == 1
    assert rows[0]["task_name"] == "Write the report"
    assert rows[0]["project_name"] == "Work"
    assert rows[0]["actual_seconds"] == 1200


def test_app_settings_are_persistent(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)

    assert get_app_setting("onboarding_complete", db_path=db_path) is None
    assert get_app_setting("missing", "fallback", db_path) == "fallback"

    set_app_setting("onboarding_complete", "1", db_path)
    assert get_app_setting("onboarding_complete", db_path=db_path) == "1"

    set_app_setting("onboarding_complete", "0", db_path)
    assert get_app_setting("onboarding_complete", db_path=db_path) == "0"

def test_invalid_status_is_rejected(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    invalid = replace(make_session("bad-session"), status="unknown")

    with pytest.raises(ValueError, match="Unsupported session status"):
        save_focus_session(invalid, db_path)


def test_local_focus_task_lifecycle(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)

    task = create_local_focus_task(
        "Read a chapter",
        description="Take notes",
        project_name="Learning",
        priority=3,
        db_path=db_path,
    )

    active = get_active_local_focus_tasks(db_path)
    assert active == [task]
    assert complete_local_focus_task(task.id, db_path) is True
    assert complete_local_focus_task(task.id, db_path) is False
    assert get_active_local_focus_tasks(db_path) == []


def test_focus_session_can_be_corrected_and_deleted(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    save_focus_session(make_session(), db_path)
    original = get_focus_sessions(db_path)[0]
    original_start = datetime.fromisoformat(str(original["started_at"]))
    corrected_start = original_start + timedelta(hours=1)

    assert update_focus_session(
        int(original["id"]),
        task_name="Corrected report",
        project_name="Admin",
        started_at=corrected_start,
        planned_minutes=20,
        actual_seconds=420,
        status="interrupted",
        notes="Pulled away after seven minutes",
        db_path=db_path,
    ) is True

    corrected = get_focus_sessions(db_path)[0]
    assert corrected["task_name"] == "Corrected report"
    assert corrected["project_name"] == "Admin"
    assert corrected["planned_minutes"] == 20
    assert corrected["actual_seconds"] == 420
    assert corrected["status"] == "interrupted"
    assert datetime.fromisoformat(str(corrected["started_at"])) == corrected_start

    assert delete_focus_session(int(corrected["id"]), db_path) is True
    assert delete_focus_session(int(corrected["id"]), db_path) is False
    assert get_focus_sessions(db_path) == []


def test_provisional_checkpoint_is_finalized_without_a_duplicate(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    checkpoint = replace(
        make_session("durable-session"),
        actual_seconds=0,
        status="continue",
        notes="Automatically saved",
    )

    assert checkpoint_focus_session(checkpoint, db_path) is True
    refreshed = replace(checkpoint, actual_seconds=300)
    assert checkpoint_focus_session(refreshed, db_path) is True
    rows = get_focus_sessions(db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "continue"
    assert rows[0]["actual_seconds"] == 300
    assert rows[0]["is_provisional"] == 1

    finalized = replace(
        refreshed,
        actual_seconds=420,
        status="completed",
        notes="Final outcome",
    )
    assert save_focus_session(finalized, db_path) is True
    rows = get_focus_sessions(db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["actual_seconds"] == 420
    assert rows[0]["notes"] == "Final outcome"
    assert rows[0]["is_provisional"] == 0

    assert checkpoint_focus_session(refreshed, db_path) is False
    assert get_focus_sessions(db_path)[0]["status"] == "completed"


def make_habit(task_id: str, content: str = "Drink water") -> Habit:
    timestamp = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    return Habit(
        todoist_task_id=task_id,
        content=content,
        project_id="health",
        project_name="Health",
        recurrence="every day",
        priority=3,
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_habit_tracking_and_checkins_are_durable(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    water = make_habit("habit-water")
    walk = make_habit("habit-walk", "Take a walk")

    set_tracked_habits([water, walk], {water.todoist_task_id}, db_path)
    tracked = get_habits(db_path)
    assert [habit.todoist_task_id for habit in tracked] == [water.todoist_task_id]
    assert tracked[0].content == water.content
    assert tracked[0].recurrence == water.recurrence

    completed_at = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)
    assert record_habit_checkin(
        water.todoist_task_id, completed_at, source="todoist", db_path=db_path
    )
    assert record_habit_checkin(
        water.todoist_task_id,
        completed_at + timedelta(minutes=1),
        source="app",
        db_path=db_path,
    )

    checkins = get_habit_checkins(db_path)
    assert len(checkins) == 1
    assert checkins[0]["todoist_task_id"] == water.todoist_task_id
    assert checkins[0]["completed_on"] == "2026-08-10"
    assert checkins[0]["source"] == "app"

    set_tracked_habits([water, walk], {walk.todoist_task_id}, db_path)
    assert [habit.todoist_task_id for habit in get_habits(db_path)] == [
        walk.todoist_task_id
    ]
    assert len(get_habits(db_path, active_only=False)) == 2


def test_generic_habit_supports_multiple_tasks_labels_and_daily_dedupe(
    tmp_path,
) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    links = [
        HabitTaskLink(
            habit_id="pending",
            todoist_task_id="task-read",
            content="Read a book",
            project_id="learning",
            project_name="Learning",
            recurrence=None,
            priority=2,
        ),
        HabitTaskLink(
            habit_id="pending",
            todoist_task_id="task-course",
            content="Watch course lesson",
            project_id="learning",
            project_name="Learning",
            recurrence=None,
            priority=3,
        ),
    ]

    habit = create_habit_definition(
        "Learn something",
        group_name="Growth",
        task_links=links,
        labels=["Learning", "@Study"],
        scheduled_weekdays=(0, 2, 4),
        db_path=db_path,
    )

    assert get_habit_definitions(db_path) == [habit]
    assert habit.scheduled_weekdays == (0, 2, 4)
    saved_links = get_habit_task_links(db_path, habit_id=habit.id)
    assert {link.todoist_task_id for link in saved_links} == {
        "task-read",
        "task-course",
    }
    assert get_habit_label_links(db_path, habit_id=habit.id) == {
        habit.id: {"learning", "study"}
    }

    completed_at = datetime(2026, 8, 10, 16, 0, tzinfo=timezone.utc)
    assert record_habit_daily_checkin(
        habit.id,
        completed_at,
        source="focus",
        todoist_task_id="task-course",
        todoist_task_name="Watch course lesson",
        db_path=db_path,
    )
    assert not record_habit_daily_checkin(
        habit.id,
        completed_at + timedelta(minutes=5),
        source="todoist",
        todoist_task_id="task-course",
        todoist_task_name="Watch course lesson",
        db_path=db_path,
    )
    rows = get_habit_daily_checkins(db_path)
    assert len(rows) == 1
    assert rows[0]["source"] == "focus"
    assert rows[0]["todoist_task_name"] == "Watch course lesson"

    assert set_habit_definition_active(habit.id, False, db_path)
    assert get_habit_definitions(db_path) == []


def test_group_icons_and_daily_reflection_are_persistent(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)

    save_habit_group_icons({"Fitness": "🏋️", "Growth": "🌱"}, db_path)
    assert get_habit_group_icons(db_path) == {
        "Fitness": "🏋️",
        "Growth": "🌱",
    }

    entry_date = datetime(2026, 8, 10).date()
    saved = save_daily_reflection(
        entry_date,
        mood=4,
        journal="Felt focused after lunch.",
        db_path=db_path,
    )
    assert get_daily_reflection(entry_date, db_path) == saved
    assert get_daily_reflections(db_path) == [saved]

    updated = save_daily_reflection(
        entry_date,
        mood=5,
        journal="Great day.",
        db_path=db_path,
    )
    assert get_daily_reflection(entry_date, db_path) == updated
    assert len(get_daily_reflections(db_path)) == 1


def test_plans_goals_preferences_reviews_and_sync_runs_are_persistent(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    timestamp = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)

    goal = create_goal(
        "Finish the course",
        description="Complete every module",
        target_date=datetime(2026, 9, 1).date(),
        db_path=db_path,
    )
    save_goal_links(
        goal.id,
        [("task", "task-1", "Study"), ("habit", "habit-1", "Daily study")],
        db_path,
    )
    assert get_goals(db_path) == [goal]
    assert len(get_goal_links(db_path, goal_id=goal.id)) == 2
    assert set_goal_status(goal.id, "paused", db_path)
    assert get_goals(db_path)[0].status == "paused"

    preference = TaskPreference(
        "task-1", "Study", "Learning", "high", 50, timestamp
    )
    save_task_preferences([preference], db_path)
    assert get_task_preferences(db_path) == {"task-1": preference}

    plan = DailyPlan(
        datetime(2026, 8, 10).date(),
        "high",
        180,
        "17:00",
        "Finish the module",
        timestamp,
    )
    save_daily_plan(
        plan,
        [
            {
                "task_id": "task-1",
                "task_name": "Study",
                "project_name": "Learning",
                "source": "todoist",
                "position": 0,
                "is_top_three": True,
            }
        ],
        db_path,
    )
    saved_plan, items = get_daily_plan(plan.plan_date, db_path)
    assert saved_plan == plan
    assert items[0]["status"] == "planned"
    assert set_daily_plan_item_status(plan.plan_date, "task-1", "completed", db_path)
    assert get_daily_plan(plan.plan_date, db_path)[1][0]["status"] == "completed"

    review = WeeklyReview(
        datetime(2026, 8, 10).date(),
        4,
        "Made progress",
        "Too many meetings",
        "Protect mornings",
        timestamp,
    )
    save_weekly_review(review, db_path)
    assert get_weekly_review(review.week_start, db_path) == review

    record_sync_run(
        "habit history",
        status="success",
        item_count=12,
        matched_count=3,
        started_at=timestamp,
        db_path=db_path,
    )
    assert get_sync_runs(db_path)[0]["matched_count"] == 3
