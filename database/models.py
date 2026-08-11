from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


SESSION_STATUSES = ("completed", "continue", "interrupted", "abandoned")


@dataclass(frozen=True, slots=True)
class LocalFocusTask:
    id: str
    content: str
    description: str
    project_name: str
    priority: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Habit:
    todoist_task_id: str
    content: str
    project_id: str | None
    project_name: str
    recurrence: str
    priority: int
    created_at: datetime
    updated_at: datetime
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class HabitDefinition:
    id: str
    name: str
    group_name: str
    created_at: datetime
    updated_at: datetime
    scheduled_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class HabitTaskLink:
    habit_id: str
    todoist_task_id: str
    content: str
    project_id: str | None
    project_name: str
    recurrence: str | None
    priority: int


@dataclass(frozen=True, slots=True)
class DailyReflection:
    entry_date: date
    mood: int
    journal: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    name: str
    description: str
    target_date: date | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TaskPreference:
    task_id: str
    task_name: str
    project_name: str
    energy_level: str
    estimated_minutes: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DailyPlan:
    plan_date: date
    energy_level: str
    available_minutes: int
    shutdown_time: str
    intention: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DailyRitual:
    ritual_date: date
    startup_completed_at: datetime | None
    shutdown_completed_at: datetime | None
    wins: str
    blockers: str
    tomorrow_first_task_id: str | None
    tomorrow_first_task_name: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WeeklyPlan:
    week_start: date
    objectives: str
    intention: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WeeklyReview:
    week_start: date
    rating: int
    wins: str
    blockers: str
    adjustments: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CalendarSource:
    id: str
    name: str
    provider: str
    event_count: int
    last_refreshed_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FocusSessionCreate:
    session_uuid: str
    todoist_task_id: str
    task_name: str
    project_id: str | None
    project_name: str | None
    started_at: datetime
    ended_at: datetime
    planned_minutes: int
    actual_seconds: int
    status: str
    notes: str = ""

    def validate(self) -> None:
        if self.status not in SESSION_STATUSES:
            raise ValueError(f"Unsupported session status: {self.status}")
        if self.planned_minutes <= 0:
            raise ValueError("Planned minutes must be positive")
        if self.actual_seconds < 0:
            raise ValueError("Actual seconds cannot be negative")
        if self.ended_at < self.started_at:
            raise ValueError("Session end cannot precede its start")
