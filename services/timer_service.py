from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from services.todoist_service import TodoistTask


RUNNING = "running"
PAUSED = "paused"
AWAITING_OUTCOME = "awaiting_outcome"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass(slots=True)
class TimerState:
    session_uuid: str
    task: TodoistTask
    planned_minutes: int
    started_at: datetime
    run_started_at: datetime | None
    accumulated_seconds: float = 0.0
    phase: str = RUNNING
    ended_at: datetime | None = None
    final_actual_seconds: int | None = None
    completion_reason: str | None = None
    saved: bool = False
    source_task_completed: bool = False
    timer_type: str = "focus"
    sound_played: bool = False
    last_checkpoint_seconds: int = -1

    @property
    def planned_seconds(self) -> int:
        return self.planned_minutes * 60


def start_timer(
    task: TodoistTask, planned_minutes: int, *, now: datetime | None = None
) -> TimerState:
    if planned_minutes <= 0:
        raise ValueError("Focus duration must be positive")
    current = _aware(now or utc_now())
    return TimerState(
        session_uuid=str(uuid4()),
        task=task,
        planned_minutes=int(planned_minutes),
        started_at=current,
        run_started_at=current,
    )


def start_break_timer(
    planned_minutes: int, *, now: datetime | None = None
) -> TimerState:
    break_task = TodoistTask(
        id="break",
        content="Break",
        description="Step away, reset, and return refreshed.",
        project_id=None,
        project_name="Break",
        section_id=None,
        priority=1,
        labels=(),
        due_date=None,
        due_datetime=None,
        url=None,
        source="break",
    )
    state = start_timer(break_task, planned_minutes, now=now)
    state.timer_type = "break"
    return state


def elapsed_seconds(state: TimerState, *, now: datetime | None = None) -> float:
    if state.final_actual_seconds is not None:
        return float(state.final_actual_seconds)
    elapsed = state.accumulated_seconds
    if state.phase == RUNNING and state.run_started_at is not None:
        current = _aware(now or utc_now())
        elapsed += max(0.0, (current - _aware(state.run_started_at)).total_seconds())
    return min(float(state.planned_seconds), elapsed)


def remaining_seconds(state: TimerState, *, now: datetime | None = None) -> float:
    return max(0.0, state.planned_seconds - elapsed_seconds(state, now=now))


def pause_timer(state: TimerState, *, now: datetime | None = None) -> None:
    if state.phase != RUNNING or state.run_started_at is None:
        return
    current = _aware(now or utc_now())
    state.accumulated_seconds = elapsed_seconds(state, now=current)
    state.run_started_at = None
    state.phase = PAUSED


def resume_timer(state: TimerState, *, now: datetime | None = None) -> None:
    if state.phase != PAUSED:
        return
    state.run_started_at = _aware(now or utc_now())
    state.phase = RUNNING


def stop_timer(state: TimerState, *, now: datetime | None = None) -> None:
    if state.phase not in (RUNNING, PAUSED):
        return
    current = _aware(now or utc_now())
    actual = elapsed_seconds(state, now=current)
    state.accumulated_seconds = actual
    state.final_actual_seconds = max(0, round(actual))
    state.run_started_at = None
    state.ended_at = current
    state.phase = AWAITING_OUTCOME
    state.completion_reason = "stopped"


def advance_timer(state: TimerState, *, now: datetime | None = None) -> bool:
    """Finish a running timer at zero. Return True only on the transition."""
    if state.phase != RUNNING:
        return False
    current = _aware(now or utc_now())
    if elapsed_seconds(state, now=current) < state.planned_seconds:
        return False
    state.accumulated_seconds = float(state.planned_seconds)
    state.final_actual_seconds = state.planned_seconds
    state.run_started_at = None
    state.ended_at = current
    state.phase = AWAITING_OUTCOME
    state.completion_reason = "natural"
    return True


def format_duration(total_seconds: float | int) -> str:
    seconds = max(0, int(round(total_seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
