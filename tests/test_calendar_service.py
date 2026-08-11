from __future__ import annotations

from datetime import date, datetime, time
from io import BytesIO
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

import pytest

from services.calendar_service import (
    CalendarEvent,
    CalendarServiceError,
    FocusWindow,
    build_focus_windows,
    count_calendar_events,
    fetch_calendar_ics,
    parse_calendar_events,
    normalize_calendar_url,
    round_up_datetime,
    schedule_tasks_into_windows,
)


NEW_YORK = ZoneInfo("America/New_York")
RECURRING_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ePomodoro Test//EN
BEGIN:VEVENT
UID:daily-meeting
DTSTART;TZID=America/New_York:20260810T100000
DTEND;TZID=America/New_York:20260810T103000
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Daily meeting
END:VEVENT
BEGIN:VEVENT
UID:transparent
DTSTART;TZID=America/New_York:20260811T130000
DTEND;TZID=America/New_York:20260811T140000
SUMMARY:Optional office hours
TRANSP:TRANSPARENT
END:VEVENT
BEGIN:VEVENT
UID:all-day
DTSTART;VALUE=DATE:20260811
DTEND;VALUE=DATE:20260812
SUMMARY:Birthday
END:VEVENT
END:VCALENDAR
"""


def test_parse_calendar_expands_recurrence_and_preserves_event_flags() -> None:
    start = datetime(2026, 8, 11, tzinfo=NEW_YORK)
    events = parse_calendar_events(
        RECURRING_ICS,
        range_start=start,
        range_end=datetime(2026, 8, 12, tzinfo=NEW_YORK),
        source_id="work",
        source_name="Work calendar",
        local_timezone=NEW_YORK,
    )

    assert count_calendar_events(RECURRING_ICS) == 3
    assert [event.title for event in events] == [
        "Birthday",
        "Daily meeting",
        "Optional office hours",
    ]
    assert events[0].all_day is True
    assert events[1].start.hour == 10
    assert events[2].transparent is True


def test_focus_windows_merge_busy_time_and_ignore_nonblocking_events() -> None:
    events = parse_calendar_events(
        RECURRING_ICS,
        range_start=datetime(2026, 8, 11, tzinfo=NEW_YORK),
        range_end=datetime(2026, 8, 12, tzinfo=NEW_YORK),
        source_id="work",
        source_name="Work calendar",
        local_timezone=NEW_YORK,
    )
    events.append(
        CalendarEvent(
            "work",
            "Work calendar",
            "overlap",
            "Follow-up",
            datetime(2026, 8, 11, 10, 20, tzinfo=NEW_YORK),
            datetime(2026, 8, 11, 11, tzinfo=NEW_YORK),
        )
    )

    windows = build_focus_windows(
        events,
        target_date=date(2026, 8, 11),
        workday_start=time(9),
        workday_end=time(15),
        local_timezone=NEW_YORK,
        event_buffer_minutes=10,
        minimum_window_minutes=20,
    )

    assert [(window.start.hour, window.start.minute) for window in windows] == [
        (9, 0),
        (11, 10),
    ]
    assert [(window.end.hour, window.end.minute) for window in windows] == [
        (9, 50),
        (15, 0),
    ]


def test_tasks_are_split_across_windows_and_report_remaining_minutes() -> None:
    windows = [
        FocusWindow(
            datetime(2026, 8, 11, 9, tzinfo=NEW_YORK),
            datetime(2026, 8, 11, 9, 30, tzinfo=NEW_YORK),
        ),
        FocusWindow(
            datetime(2026, 8, 11, 10, tzinfo=NEW_YORK),
            datetime(2026, 8, 11, 10, 45, tzinfo=NEW_YORK),
        ),
    ]
    blocks, unscheduled = schedule_tasks_into_windows(
        [
            {
                "task_id": "draft",
                "task_name": "Draft report",
                "project_name": "Work",
                "estimated_minutes": 50,
            },
            {
                "task_id": "study",
                "task_name": "Study",
                "project_name": "Learning",
                "estimated_minutes": 40,
            },
        ],
        windows,
    )

    assert [(block.task_id, block.minutes) for block in blocks] == [
        ("draft", 30),
        ("draft", 20),
        ("study", 25),
    ]
    assert blocks[0].segment_count == 2
    assert blocks[1].segment_index == 2
    assert unscheduled[0]["unscheduled_minutes"] == 15


def test_today_windows_never_begin_before_the_current_time() -> None:
    now = datetime(2026, 8, 11, 11, 37, 12, tzinfo=NEW_YORK)
    earliest = round_up_datetime(now, interval_minutes=5)
    assert earliest == datetime(2026, 8, 11, 11, 40, tzinfo=NEW_YORK)

    windows = build_focus_windows(
        [],
        target_date=date(2026, 8, 11),
        workday_start=time(8, 15),
        workday_end=time(17),
        local_timezone=NEW_YORK,
        minimum_window_minutes=20,
        not_before=earliest,
    )
    assert windows == [
        FocusWindow(
            datetime(2026, 8, 11, 11, 40, tzinfo=NEW_YORK),
            datetime(2026, 8, 11, 17, tzinfo=NEW_YORK),
        )
    ]

    assert build_focus_windows(
        [],
        target_date=date(2026, 8, 11),
        workday_start=time(8),
        workday_end=time(17),
        local_timezone=NEW_YORK,
        not_before=datetime(2026, 8, 11, 18, tzinfo=NEW_YORK),
    ) == []


def test_calendar_range_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        parse_calendar_events(
            RECURRING_ICS,
            range_start=datetime(2026, 8, 11),
            range_end=datetime(2026, 8, 12),
            source_id="work",
            source_name="Work",
        )

    with pytest.raises(CalendarServiceError, match="iCalendar"):
        count_calendar_events("not a calendar")


def test_calendar_fetch_rejects_private_hosts_and_bounds_downloads(
    monkeypatch,
) -> None:
    from services import calendar_service

    monkeypatch.setattr(
        calendar_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ],
    )

    class Response:
        headers = {"Content-Length": "45"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://calendar.example.com/private.ics"

        def read(self, _limit):
            return b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"

    class Opener:
        def open(self, _request, timeout):
            assert timeout == 15
            return Response()

    monkeypatch.setattr(calendar_service, "build_opener", lambda *_: Opener())
    assert fetch_calendar_ics(
        "https://calendar.example.com/private.ics"
    ).startswith("BEGIN:VCALENDAR")

    monkeypatch.setattr(
        calendar_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(CalendarServiceError, match="public HTTPS host"):
        fetch_calendar_ics("https://localhost/calendar.ics")


def test_calendar_fetch_reports_provider_and_network_failures(monkeypatch) -> None:
    from services import calendar_service

    monkeypatch.setattr(
        calendar_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ],
    )
    assert normalize_calendar_url(
        "webcal://calendar.example.com/private.ics"
    ) == "https://calendar.example.com/private.ics"

    class FailingOpener:
        failure: Exception

        def open(self, _request, timeout):
            raise self.failure

    opener = FailingOpener()
    monkeypatch.setattr(calendar_service, "build_opener", lambda *_: opener)

    opener.failure = HTTPError(
        "https://calendar.example.com/private.ics",
        403,
        "Forbidden",
        {},
        BytesIO(),
    )
    with pytest.raises(CalendarServiceError, match="refused access"):
        fetch_calendar_ics("https://calendar.example.com/private.ics")

    opener.failure = URLError(TimeoutError("timed out"))
    with pytest.raises(CalendarServiceError, match="timed out"):
        fetch_calendar_ics("https://calendar.example.com/private.ics")
