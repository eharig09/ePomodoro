from datetime import datetime, timezone

from services.analytics_service import calculate_analytics


def test_analytics_groups_time_and_outcomes() -> None:
    sessions = [
        {
            "started_at": "2026-08-10T13:00:00+00:00",
            "actual_seconds": 1500,
            "status": "completed",
            "project_name": "Work",
        },
        {
            "started_at": "2026-08-10T15:00:00+00:00",
            "actual_seconds": 900,
            "status": "continue",
            "project_name": "Work",
        },
        {
            "started_at": "2026-08-09T15:00:00+00:00",
            "actual_seconds": 600,
            "status": "interrupted",
            "project_name": "Personal",
        },
    ]

    metrics = calculate_analytics(
        sessions, now=datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)
    )

    assert metrics["today_seconds"] == 2400
    assert metrics["week_seconds"] == 2400
    assert metrics["completed_count"] == 1
    assert metrics["average_seconds"] == 1000
    assert metrics["by_status"] == {
        "completed": 1,
        "continue": 1,
        "interrupted": 1,
    }
    assert metrics["by_project"]["Work"] == 2400

