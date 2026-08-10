from __future__ import annotations

from datetime import datetime, tzinfo


def local_timestamp(
    value: object,
    *,
    local_timezone: tzinfo | None = None,
) -> datetime:
    """Parse a stored timestamp and return it in the local timezone."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    target_timezone = local_timezone or datetime.now().astimezone().tzinfo
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=target_timezone)
    return parsed.astimezone(target_timezone)


def format_local_datetime(
    value: object,
    *,
    local_timezone: tzinfo | None = None,
) -> str:
    local_value = local_timestamp(value, local_timezone=local_timezone)
    clock_time = local_value.strftime("%I:%M %p").lstrip("0")
    return (
        f"{local_value.strftime('%b')} {local_value.day}, {local_value.year}"
        f" at {clock_time}"
    )


def local_timezone_name() -> str:
    return datetime.now().astimezone().tzname() or "local time"
