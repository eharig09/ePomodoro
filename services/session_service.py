from __future__ import annotations

from datetime import datetime
from pathlib import Path

from database.db import checkpoint_focus_session
from database.models import FocusSessionCreate
from services.timer_service import TimerState, elapsed_seconds, utc_now


AUTO_CONTINUE_NOTE = (
    "Automatically saved as Continue while the focus timer was active."
)


def checkpoint_timer(
    state: TimerState,
    *,
    now: datetime | None = None,
    force: bool = False,
    db_path: str | Path | None = None,
) -> bool:
    if state.timer_type != "focus" or state.saved:
        return False

    current = now or utc_now()
    actual_seconds = max(0, round(elapsed_seconds(state, now=current)))
    if (
        not force
        and state.last_checkpoint_seconds >= 0
        and actual_seconds - state.last_checkpoint_seconds < 5
    ):
        return False

    session = FocusSessionCreate(
        session_uuid=state.session_uuid,
        todoist_task_id=state.task.id,
        task_name=state.task.content,
        project_id=state.task.project_id,
        project_name=state.task.project_name,
        started_at=state.started_at,
        ended_at=state.ended_at or current,
        planned_minutes=state.planned_minutes,
        actual_seconds=actual_seconds,
        status="continue",
        notes=AUTO_CONTINUE_NOTE,
    )
    written = checkpoint_focus_session(session, db_path)
    if written:
        state.last_checkpoint_seconds = actual_seconds
    return written
