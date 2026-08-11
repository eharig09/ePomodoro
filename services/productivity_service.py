from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import re
from statistics import median
from typing import Iterable, Mapping

from database.models import DailyReflection, Goal, HabitDefinition, TaskPreference
from services.datetime_service import local_timestamp
from services.todoist_service import TodoistTask


ENERGY_LEVELS = ("low", "medium", "high")
MIN_TASK_CALIBRATION_SAMPLES = 2
MIN_PROJECT_CALIBRATION_SAMPLES = 3
MIN_GLOBAL_CALIBRATION_SAMPLES = 3


def _task_due_date(task: TodoistTask) -> date | None:
    if not task.due_date:
        return None
    try:
        return date.fromisoformat(task.due_date[:10])
    except ValueError:
        return None


def _bounded_ratio(value: float) -> float:
    """Keep one unusual session from producing an implausible estimate."""
    return min(2.0, max(0.5, value))


def build_estimation_calibration(
    sessions: Iterable[Mapping[str, object]],
    *,
    min_task_samples: int = MIN_TASK_CALIBRATION_SAMPLES,
    min_project_samples: int = MIN_PROJECT_CALIBRATION_SAMPLES,
    min_global_samples: int = MIN_GLOBAL_CALIBRATION_SAMPLES,
) -> dict[str, object]:
    """Learn conservative estimate adjustments from completed focus sessions.

    Interrupted, abandoned, provisional, and zero-duration sessions are excluded
    because they do not describe how long the underlying task normally takes.
    """
    task_samples: defaultdict[str, list[float]] = defaultdict(list)
    project_samples: defaultdict[str, list[float]] = defaultdict(list)
    task_names: dict[str, str] = {}
    project_names: dict[str, str] = {}
    all_samples: list[float] = []

    for row in sessions:
        if bool(row.get("is_provisional")) or str(row.get("status")) != "completed":
            continue
        planned_minutes = int(row.get("planned_minutes", 0) or 0)
        actual_seconds = int(row.get("actual_seconds", 0) or 0)
        if planned_minutes <= 0 or actual_seconds <= 0:
            continue
        ratio = _bounded_ratio((actual_seconds / 60) / planned_minutes)
        all_samples.append(ratio)
        task_id = str(row.get("todoist_task_id") or "").strip()
        if task_id:
            task_samples[task_id].append(ratio)
            task_names[task_id] = str(row.get("task_name") or task_id).strip()
        project_label = str(row.get("project_name") or "").strip()
        project_name = project_label.casefold()
        if project_name:
            project_samples[project_name].append(ratio)
            project_names[project_name] = project_label

    task_ratios = {
        task_id: _bounded_ratio(median(values))
        for task_id, values in task_samples.items()
        if len(values) >= max(1, min_task_samples)
    }
    project_ratios = {
        project_name: _bounded_ratio(median(values))
        for project_name, values in project_samples.items()
        if len(values) >= max(1, min_project_samples)
    }
    global_ratio = (
        _bounded_ratio(median(all_samples))
        if len(all_samples) >= max(1, min_global_samples)
        else None
    )
    return {
        "sample_size": len(all_samples),
        "task_ratios": task_ratios,
        "task_samples": {
            key: len(task_samples[key]) for key in task_ratios
        },
        "task_names": {key: task_names[key] for key in task_ratios},
        "project_ratios": project_ratios,
        "project_samples": {
            key: len(project_samples[key]) for key in project_ratios
        },
        "project_names": {
            key: project_names[key] for key in project_ratios
        },
        "global_ratio": global_ratio,
        "global_samples": len(all_samples) if global_ratio is not None else 0,
    }


def calibrated_task_estimate(
    task: TodoistTask,
    preference: TaskPreference | None,
    calibration: Mapping[str, object] | None,
) -> dict[str, object]:
    """Return the configured estimate plus the best supported learned estimate."""
    base_minutes = task_estimate_minutes(task, preference)
    ratio = 1.0
    scope: str | None = None
    samples = 0

    if calibration:
        task_ratios = calibration.get("task_ratios", {})
        task_counts = calibration.get("task_samples", {})
        project_ratios = calibration.get("project_ratios", {})
        project_counts = calibration.get("project_samples", {})
        project_key = task.project_name.strip().casefold()
        if isinstance(task_ratios, Mapping) and task.id in task_ratios:
            ratio = float(task_ratios[task.id])
            samples = (
                int(task_counts.get(task.id, 0))
                if isinstance(task_counts, Mapping)
                else 0
            )
            scope = "task"
        elif isinstance(project_ratios, Mapping) and project_key in project_ratios:
            ratio = float(project_ratios[project_key])
            samples = (
                int(project_counts.get(project_key, 0))
                if isinstance(project_counts, Mapping)
                else 0
            )
            scope = "project"
        elif calibration.get("global_ratio") is not None:
            ratio = float(calibration["global_ratio"])
            samples = int(calibration.get("global_samples", 0) or 0)
            scope = "overall"

    ratio = _bounded_ratio(ratio)
    adjusted = int(round((base_minutes * ratio) / 5) * 5)
    adjusted = min(1_440, max(5 if base_minutes >= 5 else 1, adjusted))
    return {
        "base_minutes": base_minutes,
        "estimated_minutes": adjusted,
        "ratio": ratio,
        "scope": scope,
        "samples": samples,
    }


def energy_level_from_labels(labels: Iterable[str]) -> str | None:
    """Return an energy level from Todoist labels such as energy_high."""
    normalized = {
        re.sub(r"[^a-z0-9]+", "_", str(label).casefold()).strip("_")
        for label in labels
    }
    for level in reversed(ENERGY_LEVELS):
        if {f"energy_{level}", f"{level}_energy"}.intersection(normalized):
            return level
    return None


def task_energy_level(
    task: TodoistTask, preference: TaskPreference | None = None
) -> str:
    return energy_level_from_labels(task.labels) or (
        preference.energy_level if preference else "medium"
    )


def estimate_minutes_from_labels(labels: Iterable[str]) -> int | None:
    """Return a duration from labels such as 25min, 50_minutes, or time_30."""
    patterns = (
        r"^(\d{1,4})$",
        r"^(\d{1,4})_?(?:m|min|mins|minute|minutes)$",
        r"^(?:time|minutes|mins|min)_(\d{1,4})$",
    )
    for label in labels:
        normalized = re.sub(
            r"[^a-z0-9]+", "_", str(label).casefold()
        ).strip("_")
        for pattern in patterns:
            match = re.fullmatch(pattern, normalized)
            if match:
                minutes = int(match.group(1))
                if 1 <= minutes <= 1_440:
                    return minutes
    return None


def task_estimate_minutes(
    task: TodoistTask, preference: TaskPreference | None = None
) -> int:
    return estimate_minutes_from_labels(task.labels) or (
        preference.estimated_minutes if preference else 25
    )


def recommend_tasks(
    tasks: Iterable[TodoistTask],
    *,
    preferences: Mapping[str, TaskPreference],
    current_energy: str,
    available_minutes: int,
    planned_task_ids: Iterable[str] = (),
    top_task_ids: Iterable[str] = (),
    goal_task_ids: Iterable[str] = (),
    today: date | None = None,
    estimation_calibration: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    if current_energy not in ENERGY_LEVELS:
        raise ValueError("Current energy must be low, medium, or high")
    target_date = today or date.today()
    planned = set(planned_task_ids)
    top = set(top_task_ids)
    goal_linked = set(goal_task_ids)
    energy_index = {level: index for index, level in enumerate(ENERGY_LEVELS)}
    recommendations: list[dict[str, object]] = []

    for task in tasks:
        preference = preferences.get(task.id)
        task_energy = task_energy_level(task, preference)
        estimate_detail = calibrated_task_estimate(
            task, preference, estimation_calibration
        )
        estimate = int(estimate_detail["estimated_minutes"])
        score = task.priority * 10
        reasons: list[str] = [task.priority_label]

        if task.id in top:
            score += 40
            reasons.append("top task")
        elif task.id in planned:
            score += 18
            reasons.append("in today’s plan")
        due = _task_due_date(task)
        if due:
            if due < target_date:
                score += 35
                reasons.append("overdue")
            elif due == target_date:
                score += 28
                reasons.append("due today")
        energy_gap = abs(energy_index[task_energy] - energy_index[current_energy])
        if energy_gap == 0:
            score += 20
            reasons.append(f"fits {current_energy} energy")
        elif energy_gap == 1:
            score += 7
        else:
            score -= 12
        if estimate <= available_minutes:
            score += 12
            reasons.append(f"fits {estimate} min")
        else:
            score -= min(20, (estimate - available_minutes) // 10)
        if task.id in goal_linked:
            score += 14
            reasons.append("supports a goal")
        if (
            estimate_detail["scope"] is not None
            and estimate != int(estimate_detail["base_minutes"])
        ):
            reasons.append(f"history suggests {estimate} min")

        recommendations.append(
            {
                "task": task,
                "score": score,
                "energy_level": task_energy,
                "estimated_minutes": estimate,
                "base_estimated_minutes": estimate_detail["base_minutes"],
                "estimate_scope": estimate_detail["scope"],
                "estimate_samples": estimate_detail["samples"],
                "estimate_ratio": estimate_detail["ratio"],
                "reasons": reasons,
            }
        )

    return sorted(
        recommendations,
        key=lambda item: (
            -int(item["score"]),
            -item["task"].priority,
            item["task"].content.casefold(),
        ),
    )


def build_daily_plan_suggestion(
    tasks: Iterable[TodoistTask],
    *,
    preferences: Mapping[str, TaskPreference],
    current_energy: str,
    available_minutes: int,
    goal_task_ids: Iterable[str] = (),
    today: date | None = None,
    buffer_percent: int = 20,
    max_tasks: int = 8,
    estimation_calibration: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Choose a ranked set of tasks that fits inside usable daily capacity."""
    if not 1 <= available_minutes <= 1_440:
        raise ValueError("Available minutes must be between 1 and 1,440")
    if not 0 <= buffer_percent <= 50:
        raise ValueError("Buffer percent must be between 0 and 50")
    if not 1 <= max_tasks <= 20:
        raise ValueError("Maximum tasks must be between 1 and 20")

    target_date = today or date.today()
    usable_minutes = max(1, int(available_minutes * (100 - buffer_percent) / 100))
    ranked = recommend_tasks(
        tasks,
        preferences=preferences,
        current_energy=current_energy,
        available_minutes=usable_minutes,
        goal_task_ids=goal_task_ids,
        today=target_date,
        estimation_calibration=estimation_calibration,
    )

    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    remaining = usable_minutes
    for recommendation in ranked:
        if len(selected) >= max_tasks:
            break
        estimate = int(recommendation["estimated_minutes"])
        task = recommendation["task"]
        if task.id in selected_ids or estimate > remaining:
            continue
        selected.append(recommendation)
        selected_ids.add(task.id)
        remaining -= estimate

    overdue_or_due = [
        recommendation
        for recommendation in ranked
        if (due := _task_due_date(recommendation["task"])) is not None
        and due <= target_date
        and recommendation["task"].id not in selected_ids
    ]
    return {
        "items": selected,
        "available_minutes": available_minutes,
        "usable_minutes": usable_minutes,
        "buffer_minutes": available_minutes - usable_minutes,
        "planned_minutes": usable_minutes - remaining,
        "remaining_minutes": remaining,
        "unplanned_due": overdue_or_due,
    }


def build_focus_profile(
    sessions: Iterable[Mapping[str, object]],
    reflections: Iterable[DailyReflection] = (),
) -> dict[str, object]:
    rows = [
        row
        for row in sessions
        if not bool(row.get("is_provisional")) and int(row.get("actual_seconds", 0)) > 0
    ]
    completed = [row for row in rows if str(row.get("status")) == "completed"]
    completed_minutes = [int(row["actual_seconds"]) / 60 for row in completed]
    suggested_minutes = 25
    if completed_minutes:
        suggested_minutes = max(
            10, min(90, int(round(median(completed_minutes) / 5) * 5))
        )

    period_rows: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        hour = local_timestamp(row["started_at"]).hour
        period = "Morning" if hour < 12 else "Afternoon" if hour < 17 else "Evening"
        period_rows[period].append(row)
    period_stats: dict[str, dict[str, float | int]] = {}
    for period, period_sessions in period_rows.items():
        complete_count = sum(
            str(row.get("status")) == "completed" for row in period_sessions
        )
        period_stats[period] = {
            "sessions": len(period_sessions),
            "completion_rate": complete_count / len(period_sessions),
            "average_minutes": round(
                sum(int(row["actual_seconds"]) for row in period_sessions)
                / len(period_sessions)
                / 60,
                1,
            ),
        }
    best_period = None
    eligible_periods = {
        period: stats
        for period, stats in period_stats.items()
        if int(stats["sessions"]) >= 2
    }
    if eligible_periods:
        best_period = max(
            eligible_periods,
            key=lambda period: (
                float(eligible_periods[period]["completion_rate"]),
                float(eligible_periods[period]["average_minutes"]),
            ),
        )

    accuracy_rows = [row for row in rows if int(row.get("planned_minutes", 0)) > 0]
    plan_accuracy = None
    if accuracy_rows:
        actual = sum(int(row["actual_seconds"]) / 60 for row in accuracy_rows)
        planned = sum(int(row["planned_minutes"]) for row in accuracy_rows)
        plan_accuracy = actual / planned if planned else None

    reflection_by_date = {reflection.entry_date: reflection for reflection in reflections}
    mood_minutes: defaultdict[int, list[float]] = defaultdict(list)
    focus_by_date: defaultdict[date, float] = defaultdict(float)
    for row in rows:
        focus_by_date[local_timestamp(row["started_at"]).date()] += (
            int(row["actual_seconds"]) / 60
        )
    for focus_date, minutes in focus_by_date.items():
        reflection = reflection_by_date.get(focus_date)
        if reflection:
            mood_minutes[reflection.mood].append(minutes)

    return {
        "sample_size": len(rows),
        "suggested_minutes": suggested_minutes,
        "best_period": best_period,
        "period_stats": period_stats,
        "plan_accuracy": plan_accuracy,
        "mood_focus_minutes": {
            mood: round(sum(values) / len(values), 1)
            for mood, values in sorted(mood_minutes.items())
        },
    }


def calculate_goal_activity(
    goals: Iterable[Goal],
    links: Iterable[Mapping[str, object]],
    sessions: Iterable[Mapping[str, object]],
    habit_checkins: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    task_goals: defaultdict[str, set[str]] = defaultdict(set)
    habit_goals: defaultdict[str, set[str]] = defaultdict(set)
    linked_count: defaultdict[str, int] = defaultdict(int)
    for link in links:
        goal_id = str(link["goal_id"])
        entity_id = str(link["entity_id"])
        linked_count[goal_id] += 1
        if str(link["entity_type"]) == "task":
            task_goals[entity_id].add(goal_id)
        else:
            habit_goals[entity_id].add(goal_id)

    activity = {
        goal.id: {
            "linked_count": linked_count[goal.id],
            "focus_seconds": 0,
            "habit_checkins": 0,
            "last_activity": None,
        }
        for goal in goals
    }
    for row in sessions:
        if bool(row.get("is_provisional")):
            continue
        task_id = str(row.get("todoist_task_id") or "")
        for goal_id in task_goals.get(task_id, set()):
            if goal_id not in activity:
                continue
            activity[goal_id]["focus_seconds"] += int(row.get("actual_seconds", 0))
            activity_date = local_timestamp(row["started_at"]).date()
            previous = activity[goal_id]["last_activity"]
            if previous is None or activity_date > previous:
                activity[goal_id]["last_activity"] = activity_date
    for row in habit_checkins:
        habit_id = str(row.get("habit_id") or "")
        for goal_id in habit_goals.get(habit_id, set()):
            if goal_id not in activity:
                continue
            activity[goal_id]["habit_checkins"] += 1
            activity_date = date.fromisoformat(str(row["completed_on"]))
            previous = activity[goal_id]["last_activity"]
            if previous is None or activity_date > previous:
                activity[goal_id]["last_activity"] = activity_date
    return activity


def calculate_weekly_metrics(
    sessions: Iterable[Mapping[str, object]],
    habits: Iterable[HabitDefinition],
    habit_checkins: Iterable[Mapping[str, object]],
    *,
    week_start: date,
) -> dict[str, object]:
    week_end = week_start + timedelta(days=6)
    session_rows = [
        row
        for row in sessions
        if not bool(row.get("is_provisional"))
        and week_start <= local_timestamp(row["started_at"]).date() <= week_end
    ]
    total_seconds = sum(int(row.get("actual_seconds", 0)) for row in session_rows)
    completed_sessions = sum(
        str(row.get("status")) == "completed" for row in session_rows
    )
    planned_minutes = sum(int(row.get("planned_minutes", 0)) for row in session_rows)
    actual_minutes = total_seconds / 60
    by_project: defaultdict[str, int] = defaultdict(int)
    for row in session_rows:
        by_project[str(row.get("project_name") or "Unknown project")] += int(
            row.get("actual_seconds", 0)
        )

    checkins = {
        (str(row["habit_id"]), date.fromisoformat(str(row["completed_on"])))
        for row in habit_checkins
        if week_start <= date.fromisoformat(str(row["completed_on"])) <= week_end
    }
    habit_due = 0
    habit_done = 0
    today = date.today()
    for habit in habits:
        created_on = local_timestamp(habit.created_at).date()
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            if day > today or day < created_on:
                continue
            if day.weekday() in habit.scheduled_weekdays:
                habit_due += 1
                habit_done += (habit.id, day) in checkins

    return {
        "week_end": week_end,
        "session_count": len(session_rows),
        "completed_sessions": completed_sessions,
        "focus_seconds": total_seconds,
        "planned_minutes": planned_minutes,
        "actual_minutes": round(actual_minutes, 1),
        "plan_ratio": actual_minutes / planned_minutes if planned_minutes else None,
        "habit_due": habit_due,
        "habit_done": habit_done,
        "habit_rate": habit_done / habit_due if habit_due else None,
        "by_project": dict(
            sorted(by_project.items(), key=lambda item: item[1], reverse=True)
        ),
    }
