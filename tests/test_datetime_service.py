from datetime import datetime, timedelta, timezone

from services.datetime_service import format_local_datetime, local_timestamp


EASTERN_DAYLIGHT = timezone(timedelta(hours=-4), name="EDT")


def test_utc_timestamp_is_converted_to_requested_local_timezone() -> None:
    converted = local_timestamp(
        "2026-08-10T15:30:00Z", local_timezone=EASTERN_DAYLIGHT
    )

    assert converted == datetime(2026, 8, 10, 11, 30, tzinfo=EASTERN_DAYLIGHT)


def test_local_datetime_has_readable_display_format() -> None:
    assert format_local_datetime(
        "2026-08-10T15:30:00+00:00", local_timezone=EASTERN_DAYLIGHT
    ) == "Aug 10, 2026 at 11:30 AM"
