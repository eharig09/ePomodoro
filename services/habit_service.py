from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from database.db import (
    get_habit_definitions,
    get_habit_label_links,
    get_habit_task_links,
    record_habit_daily_checkin,
)
from database.models import Habit, HabitDefinition, HabitTaskLink
from services.todoist_service import TodoistService, TodoistTask


def habit_from_todoist(task: TodoistTask, *, now: datetime | None = None) -> Habit:
    if not task.is_recurring:
        raise ValueError("Only recurring Todoist tasks can be tracked as habits")
    timestamp = now or datetime.now(timezone.utc)
    return Habit(
        todoist_task_id=task.id,
        content=task.content,
        project_id=task.project_id,
        project_name=task.project_name,
        recurrence=task.due_string or "Recurring",
        priority=task.priority,
        created_at=timestamp,
        updated_at=timestamp,
    )


def match_completed_task_to_habit(
    task: TodoistTask,
    habits: Iterable[Habit],
) -> Habit | None:
    """Resolve Todoist's archived occurrence IDs to a tracked recurring task."""
    tracked = list(habits)
    direct = next(
        (habit for habit in tracked if habit.todoist_task_id == task.id),
        None,
    )
    if direct is not None:
        return direct
    if not task.is_recurring:
        return None

    same_name = [
        habit
        for habit in tracked
        if habit.content.casefold() == task.content.casefold()
    ]
    same_project = [
        habit for habit in same_name if habit.project_id == task.project_id
    ]
    if len(same_project) == 1:
        return same_project[0]

    recurrence = (task.due_string or "").casefold()
    same_recurrence = [
        habit
        for habit in same_project
        if habit.recurrence.casefold() == recurrence
    ]
    if len(same_recurrence) == 1:
        return same_recurrence[0]

    if len(same_name) == 1:
        return same_name[0]
    return None


def task_link_from_todoist(
    task: TodoistTask,
    *,
    habit_id: str = "pending",
) -> HabitTaskLink:
    return HabitTaskLink(
        habit_id=habit_id,
        todoist_task_id=task.id,
        content=task.content,
        project_id=task.project_id,
        project_name=task.project_name,
        recurrence=task.due_string,
        priority=task.priority,
    )


def matching_habits_for_task(
    task: TodoistTask,
    *,
    habits: Iterable[HabitDefinition] | None = None,
    task_links: Iterable[HabitTaskLink] | None = None,
    label_links: Mapping[str, set[str]] | None = None,
    db_path: str | Path | None = None,
) -> list[HabitDefinition]:
    tracked = (
        list(habits)
        if habits is not None
        else get_habit_definitions(db_path)
    )
    links = (
        list(task_links)
        if task_links is not None
        else get_habit_task_links(db_path)
    )
    labels_by_habit = (
        dict(label_links)
        if label_links is not None
        else get_habit_label_links(db_path)
    )
    task_labels = {label.casefold() for label in task.labels}
    links_by_habit: defaultdict[str, list[HabitTaskLink]] = defaultdict(list)
    for link in links:
        links_by_habit[link.habit_id].append(link)

    matches: list[HabitDefinition] = []
    for habit in tracked:
        explicit_links = links_by_habit.get(habit.id, [])
        direct_match = any(link.todoist_task_id == task.id for link in explicit_links)
        archived_recurring_match = task.is_recurring and any(
            link.content.casefold() == task.content.casefold()
            and link.project_id == task.project_id
            and (
                not link.recurrence
                or not task.due_string
                or link.recurrence.casefold() == task.due_string.casefold()
            )
            for link in explicit_links
        )
        label_match = bool(
            task_labels.intersection(labels_by_habit.get(habit.id, set()))
        )
        if direct_match or archived_recurring_match or label_match:
            matches.append(habit)
    return matches


def tasks_matching_habit(
    habit_id: str,
    tasks: Iterable[TodoistTask],
    *,
    task_links: Iterable[HabitTaskLink] | None = None,
    label_links: Mapping[str, set[str]] | None = None,
) -> list[TodoistTask]:
    links = list(task_links) if task_links is not None else get_habit_task_links()
    labels_by_habit = (
        dict(label_links) if label_links is not None else get_habit_label_links()
    )
    task_ids = {
        link.todoist_task_id for link in links if link.habit_id == habit_id
    }
    labels = labels_by_habit.get(habit_id, set())
    matched = [
        task
        for task in tasks
        if task.id in task_ids
        or bool(labels.intersection(label.casefold() for label in task.labels))
    ]
    return sorted(
        matched,
        key=lambda task: (
            task.due_date or "9999-12-31",
            -task.priority,
            task.content.casefold(),
        ),
    )


def record_task_completion(
    task: TodoistTask,
    *,
    completed_at: datetime | None = None,
    source: str,
    db_path: str | Path | None = None,
) -> list[HabitDefinition]:
    timestamp = completed_at or datetime.now(timezone.utc)
    matches = matching_habits_for_task(task, db_path=db_path)
    for habit in matches:
        record_habit_daily_checkin(
            habit.id,
            timestamp,
            source=source,
            todoist_task_id=task.id,
            todoist_task_name=task.content,
            db_path=db_path,
        )
    return matches


def sync_completed_habit_history(
    token: str,
    *,
    now: datetime | None = None,
    days: int = 89,
    service: TodoistService | None = None,
    project_names: Mapping[str, str] | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[TodoistTask], int]:
    if not 1 <= days <= 89:
        raise ValueError("Habit history sync must cover between 1 and 89 days")
    current = now or datetime.now(timezone.utc)
    todoist = service or TodoistService(token)
    since = current - timedelta(days=days)
    archived_tasks = todoist.get_completed_tasks(
        since=since,
        until=current,
        project_names=project_names,
    )
    activity_tasks = todoist.get_completed_task_events(
        since=since,
        until=current,
        project_names=project_names,
    )
    completed_by_event = {
        (task.id, task.completed_at): task
        for task in [*archived_tasks, *activity_tasks]
    }
    completed_tasks = sorted(
        completed_by_event.values(),
        key=lambda task: task.completed_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    matched_habits = 0
    for task in completed_tasks:
        if task.completed_at is None:
            continue
        matched_habits += len(
            record_task_completion(
                task,
                completed_at=task.completed_at,
                source="todoist",
                db_path=db_path,
            )
        )
    return completed_tasks, matched_habits


def checkin_dates_by_habit(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, set[date]]:
    grouped: defaultdict[str, set[date]] = defaultdict(set)
    for row in rows:
        habit_key = row.get("habit_id", row.get("todoist_task_id"))
        if habit_key is None:
            continue
        grouped[str(habit_key)].add(
            date.fromisoformat(str(row["completed_on"]))
        )
    return dict(grouped)


def _validated_schedule(scheduled_weekdays: Iterable[int]) -> set[int]:
    schedule = {int(weekday) for weekday in scheduled_weekdays}
    if not schedule or any(weekday not in range(7) for weekday in schedule):
        raise ValueError("A habit schedule must contain at least one valid weekday")
    return schedule


def _previous_scheduled_date(day: date, schedule: set[int]) -> date:
    cursor = day - timedelta(days=1)
    while cursor.weekday() not in schedule:
        cursor -= timedelta(days=1)
    return cursor


def _next_scheduled_date(day: date, schedule: set[int]) -> date:
    cursor = day + timedelta(days=1)
    while cursor.weekday() not in schedule:
        cursor += timedelta(days=1)
    return cursor


def current_streak(
    completed_dates: Iterable[date],
    *,
    today: date | None = None,
    scheduled_weekdays: Iterable[int] = range(7),
) -> int:
    days = set(completed_dates)
    target = today or date.today()
    schedule = _validated_schedule(scheduled_weekdays)
    cursor = target
    while cursor.weekday() not in schedule:
        cursor -= timedelta(days=1)
    if cursor == target and cursor not in days:
        cursor = _previous_scheduled_date(cursor, schedule)

    streak = 0
    while cursor in days:
        streak += 1
        cursor = _previous_scheduled_date(cursor, schedule)
    return streak


def best_streak(
    completed_dates: Iterable[date],
    *,
    today: date | None = None,
    scheduled_weekdays: Iterable[int] = range(7),
) -> int:
    target = today or date.today()
    schedule = _validated_schedule(scheduled_weekdays)
    scheduled_completions = sorted(
        {
            completed_on
            for completed_on in completed_dates
            if completed_on <= target and completed_on.weekday() in schedule
        }
    )
    longest = 0
    running = 0
    previous: date | None = None
    for completed_on in scheduled_completions:
        if previous is not None and completed_on == _next_scheduled_date(
            previous, schedule
        ):
            running += 1
        else:
            running = 1
        longest = max(longest, running)
        previous = completed_on
    return longest


def recent_dates(*, today: date | None = None, days: int = 7) -> list[date]:
    if days <= 0:
        raise ValueError("Recent date window must be positive")
    target = today or date.today()
    return [target - timedelta(days=offset) for offset in reversed(range(days))]
