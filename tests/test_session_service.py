from datetime import datetime, timedelta, timezone

from database.db import get_focus_sessions, init_db
from services.session_service import checkpoint_timer
from services.timer_service import start_break_timer, start_timer
from services.todoist_service import TodoistTask


def focus_task() -> TodoistTask:
    return TodoistTask(
        id="local:durable",
        content="Durable focus",
        description="",
        project_id=None,
        project_name="Local",
        section_id=None,
        priority=1,
        labels=(),
        due_date=None,
        due_datetime=None,
        url=None,
        source="local",
    )


def test_timer_checkpoint_is_throttled_and_breaks_are_excluded(tmp_path) -> None:
    db_path = tmp_path / "focus.db"
    init_db(db_path)
    start = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    state = start_timer(focus_task(), 25, now=start)

    assert checkpoint_timer(state, now=start, force=True, db_path=db_path) is True
    assert (
        checkpoint_timer(
            state, now=start + timedelta(seconds=3), db_path=db_path
        )
        is False
    )
    assert (
        checkpoint_timer(
            state, now=start + timedelta(seconds=6), db_path=db_path
        )
        is True
    )
    rows = get_focus_sessions(db_path)
    assert len(rows) == 1
    assert rows[0]["actual_seconds"] == 6
    assert rows[0]["status"] == "continue"

    break_state = start_break_timer(5, now=start)
    assert checkpoint_timer(break_state, now=start, force=True, db_path=db_path) is False
    assert len(get_focus_sessions(db_path)) == 1
