from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping

from services.datetime_service import local_timestamp


def parse_timestamp(value: object) -> datetime:
    return local_timestamp(value)


def calculate_analytics(
    sessions: Iterable[Mapping[str, object]], *, now: datetime | None = None
) -> dict[str, object]:
    rows = list(sessions)
    current = (now or datetime.now().astimezone()).astimezone()
    today = current.date()
    week_start = today - timedelta(days=today.weekday())

    total_seconds = sum(int(row["actual_seconds"]) for row in rows)
    today_seconds = 0
    week_seconds = 0
    completed_count = 0
    by_status: defaultdict[str, int] = defaultdict(int)
    by_project: defaultdict[str, int] = defaultdict(int)
    by_day: defaultdict[date, int] = defaultdict(int)

    for row in rows:
        seconds = int(row["actual_seconds"])
        local_date = parse_timestamp(row["started_at"]).date()
        if local_date == today:
            today_seconds += seconds
        if week_start <= local_date <= today:
            week_seconds += seconds
        status = str(row["status"])
        by_status[status] += 1
        if status == "completed":
            completed_count += 1
        project = str(row.get("project_name") or "Unknown project")
        by_project[project] += seconds
        by_day[local_date] += seconds

    return {
        "today_seconds": today_seconds,
        "week_seconds": week_seconds,
        "completed_count": completed_count,
        "average_seconds": round(total_seconds / len(rows)) if rows else 0,
        "by_status": dict(sorted(by_status.items())),
        "by_project": dict(
            sorted(by_project.items(), key=lambda item: item[1], reverse=True)
        ),
        "by_day": dict(sorted(by_day.items())),
    }
