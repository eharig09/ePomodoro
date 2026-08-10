from datetime import datetime, timedelta, timezone

from services.timer_service import (
    AWAITING_OUTCOME,
    PAUSED,
    advance_timer,
    elapsed_seconds,
    pause_timer,
    remaining_seconds,
    resume_timer,
    start_break_timer,
    start_timer,
    stop_timer,
)
from services.todoist_service import TodoistTask


def task() -> TodoistTask:
    return TodoistTask(
        id="123",
        content="Write the report",
        description="",
        project_id="42",
        project_name="Work",
        section_id=None,
        priority=3,
        labels=("deep-work",),
        due_date="2026-08-10",
        due_datetime=None,
        url="https://app.todoist.com/app/task/123",
    )


def test_elapsed_and_remaining_use_timestamps_without_drift() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_timer(task(), 25, now=start)

    now = start + timedelta(minutes=4, seconds=12)
    assert elapsed_seconds(state, now=now) == 252
    assert remaining_seconds(state, now=now) == 1248


def test_paused_time_is_not_counted() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_timer(task(), 25, now=start)
    pause_timer(state, now=start + timedelta(minutes=5))

    assert state.phase == PAUSED
    assert elapsed_seconds(state, now=start + timedelta(minutes=20)) == 300

    resume_timer(state, now=start + timedelta(minutes=20))
    assert elapsed_seconds(state, now=start + timedelta(minutes=22)) == 420


def test_natural_completion_is_clamped_to_planned_duration() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_timer(task(), 1, now=start)

    transitioned = advance_timer(state, now=start + timedelta(seconds=63))

    assert transitioned is True
    assert state.phase == AWAITING_OUTCOME
    assert state.final_actual_seconds == 60
    assert state.completion_reason == "natural"
    assert advance_timer(state, now=start + timedelta(seconds=64)) is False


def test_stop_early_records_actual_focus_time() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_timer(task(), 25, now=start)

    stop_timer(state, now=start + timedelta(seconds=95))

    assert state.phase == AWAITING_OUTCOME
    assert state.final_actual_seconds == 95
    assert state.completion_reason == "stopped"


def test_break_timer_uses_timer_logic_but_is_identified_separately() -> None:
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_break_timer(5, now=start)

    assert state.timer_type == "break"
    assert state.task.source == "break"
    assert state.task.content == "Break"
    assert remaining_seconds(state, now=start + timedelta(minutes=2)) == 180

