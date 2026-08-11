from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
import ipaddress
import socket
import ssl
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from icalendar import Calendar
import recurring_ical_events


MAX_ICS_BYTES = 5_000_000


class CalendarServiceError(RuntimeError):
    """A user-safe calendar connection or parsing error."""


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    source_id: str
    source_name: str
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    transparent: bool = False


@dataclass(frozen=True, slots=True)
class FocusWindow:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return max(0, round((self.end - self.start).total_seconds() / 60))


@dataclass(frozen=True, slots=True)
class TaskTimeBlock:
    task_id: str
    task_name: str
    project_name: str
    start: datetime
    end: datetime
    minutes: int
    segment_index: int = 1
    segment_count: int = 1


def round_up_datetime(value: datetime, *, interval_minutes: int = 5) -> datetime:
    """Round an aware or naive datetime up to the next scheduling boundary."""
    if not 1 <= interval_minutes <= 60:
        raise ValueError("Scheduling interval must be between 1 and 60 minutes")
    base = value.replace(second=0, microsecond=0)
    elapsed = value.minute % interval_minutes
    needs_next = elapsed != 0 or value.second != 0 or value.microsecond != 0
    minutes_to_add = (
        interval_minutes - elapsed
        if needs_next and elapsed
        else interval_minutes
        if needs_next
        else 0
    )
    return base + timedelta(minutes=minutes_to_add)


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        safe_url = _validate_public_https_url(new_url)
        return super().redirect_request(
            request, file_pointer, code, message, headers, safe_url
        )


def normalize_calendar_url(url: str) -> str:
    """Normalize provider subscription links without weakening HTTPS-only access."""
    clean_url = url.strip()
    try:
        parsed = urlparse(clean_url)
    except ValueError as exc:
        raise CalendarServiceError("Enter a valid HTTPS iCalendar URL") from exc
    if parsed.scheme.lower() == "webcal":
        parsed = parsed._replace(scheme="https")
        clean_url = urlunparse(parsed)
    return clean_url


def _validate_public_https_url(url: str) -> str:
    clean_url = normalize_calendar_url(url)
    try:
        parsed = urlparse(clean_url)
        port = parsed.port or 443
    except ValueError as exc:
        raise CalendarServiceError("Enter a valid HTTPS iCalendar URL") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CalendarServiceError("Enter a valid HTTPS iCalendar URL")
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except OSError as exc:
        raise CalendarServiceError("The calendar host could not be reached") from exc
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise CalendarServiceError("Calendar links must use a public HTTPS host")
    return clean_url


def _http_error_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return (
            "The calendar provider refused access. Copy the private or secret ICS "
            "subscription link, not the calendar webpage or sharing page."
        )
    if status_code == 404:
        return (
            "The calendar link was not found. It may be incomplete, expired, or "
            "reset; copy a fresh ICS subscription link from the provider."
        )
    if status_code == 429:
        return "The calendar provider is rate limiting requests. Wait a minute and retry."
    if 500 <= status_code <= 599:
        return (
            "The calendar provider is temporarily unavailable "
            f"(HTTP {status_code}). Try again later."
        )
    return (
        f"The calendar provider returned HTTP {status_code}. Make sure this is the "
        "ICS subscription link rather than a calendar webpage."
    )


def _url_error_message(reason: object) -> str:
    if isinstance(reason, ssl.SSLCertVerificationError):
        return (
            "The calendar's secure certificate could not be verified. Check the "
            "computer clock, VPN, antivirus HTTPS scanning, or provider link."
        )
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "The calendar connection timed out. Check the network or VPN and retry."
    if isinstance(reason, socket.gaierror):
        return "The calendar host could not be found. Check the copied link and network."
    return (
        "The network connection to the calendar failed. Check internet access, VPN, "
        "firewall, or antivirus HTTPS scanning and retry."
    )


def fetch_calendar_ics(url: str, *, timeout_seconds: float = 15) -> str:
    """Download a bounded ICS feed without exposing private network addresses."""
    clean_url = _validate_public_https_url(url)
    request = Request(
        clean_url,
        headers={
            "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
            "User-Agent": "ePomodoro/1 calendar-availability",
        },
    )
    opener = build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            _validate_public_https_url(final_url)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ICS_BYTES:
                raise CalendarServiceError("The calendar feed is larger than 5 MB")
            payload = response.read(MAX_ICS_BYTES + 1)
    except CalendarServiceError:
        raise
    except HTTPError as exc:
        raise CalendarServiceError(_http_error_message(exc.code)) from exc
    except URLError as exc:
        raise CalendarServiceError(_url_error_message(exc.reason)) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise CalendarServiceError(
            "The calendar connection timed out. Check the network or VPN and retry."
        ) from exc
    except (OSError, ValueError) as exc:
        raise CalendarServiceError(
            "The calendar provider returned an invalid response. Copy a fresh ICS "
            "subscription link and retry."
        ) from exc
    if len(payload) > MAX_ICS_BYTES:
        raise CalendarServiceError("The calendar feed is larger than 5 MB")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CalendarServiceError("The calendar feed is not valid UTF-8") from exc
    if "BEGIN:VCALENDAR" not in text[:1_000].upper():
        raise CalendarServiceError("That link did not return an iCalendar feed")
    return text


def count_calendar_events(ics_data: str | bytes) -> int:
    calendar = _parse_calendar(ics_data)
    return len(calendar.walk("VEVENT"))


def _parse_calendar(ics_data: str | bytes) -> Calendar:
    if not ics_data or len(
        ics_data.encode("utf-8") if isinstance(ics_data, str) else ics_data
    ) > MAX_ICS_BYTES:
        raise CalendarServiceError("Calendar data must be a valid file under 5 MB")
    try:
        return Calendar.from_ical(ics_data)
    except (ValueError, TypeError) as exc:
        raise CalendarServiceError("Focus could not read that iCalendar data") from exc


def _as_local_datetime(
    value: object,
    *,
    local_timezone: tzinfo,
) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        localized = (
            value.replace(tzinfo=local_timezone)
            if value.tzinfo is None
            else value.astimezone(local_timezone)
        )
        return localized, False
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=local_timezone), True
    raise CalendarServiceError("A calendar event has an invalid date or time")


def parse_calendar_events(
    ics_data: str | bytes,
    *,
    range_start: datetime,
    range_end: datetime,
    source_id: str,
    source_name: str,
    local_timezone: tzinfo | None = None,
) -> list[CalendarEvent]:
    """Expand recurring events that overlap an aware local time range."""
    if range_start.tzinfo is None or range_end.tzinfo is None:
        raise ValueError("Calendar ranges must include a timezone")
    if range_end <= range_start:
        raise ValueError("Calendar range end must follow its start")
    target_timezone = local_timezone or range_start.tzinfo
    calendar = _parse_calendar(ics_data)
    try:
        components = recurring_ical_events.of(
            calendar,
            skip_bad_series=True,
        ).between(range_start, range_end)
    except (ValueError, TypeError) as exc:
        raise CalendarServiceError(
            "Focus could not expand recurring calendar events"
        ) from exc

    events: list[CalendarEvent] = []
    seen: set[tuple[str, datetime, datetime]] = set()
    for component in components:
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        try:
            raw_start = component.decoded("DTSTART")
            raw_end = component.decoded("DTEND")
            start, all_day = _as_local_datetime(
                raw_start,
                local_timezone=target_timezone,
            )
            end, end_all_day = _as_local_datetime(
                raw_end,
                local_timezone=target_timezone,
            )
        except (KeyError, ValueError, TypeError, CalendarServiceError):
            continue
        if end <= start:
            end = start + (timedelta(days=1) if all_day else timedelta(minutes=1))
        if end <= range_start or start >= range_end:
            continue
        uid = str(component.get("UID") or f"event-{len(events) + 1}")
        key = (uid, start, end)
        if key in seen:
            continue
        seen.add(key)
        title = str(component.get("SUMMARY") or "Busy").strip() or "Busy"
        events.append(
            CalendarEvent(
                source_id=source_id,
                source_name=source_name,
                uid=uid,
                title=title[:300],
                start=start,
                end=end,
                all_day=all_day or end_all_day,
                transparent=str(component.get("TRANSP", "")).upper()
                == "TRANSPARENT",
            )
        )
    return sorted(events, key=lambda event: (event.start, event.end, event.title))


def build_focus_windows(
    events: Iterable[CalendarEvent],
    *,
    target_date: date,
    workday_start: time,
    workday_end: time,
    local_timezone: tzinfo,
    event_buffer_minutes: int = 10,
    minimum_window_minutes: int = 20,
    all_day_events_block: bool = False,
    not_before: datetime | None = None,
) -> list[FocusWindow]:
    if workday_end <= workday_start:
        raise ValueError("Workday end must be after workday start")
    if not 0 <= event_buffer_minutes <= 120:
        raise ValueError("Event buffer must be between 0 and 120 minutes")
    if not 5 <= minimum_window_minutes <= 240:
        raise ValueError("Minimum focus window must be between 5 and 240 minutes")
    day_start = datetime.combine(target_date, workday_start, tzinfo=local_timezone)
    day_end = datetime.combine(target_date, workday_end, tzinfo=local_timezone)
    if not_before is not None:
        if not_before.tzinfo is None:
            raise ValueError("Earliest focus time must include a timezone")
        day_start = max(day_start, not_before.astimezone(local_timezone))
    if day_start >= day_end:
        return []
    buffer = timedelta(minutes=event_buffer_minutes)
    busy: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.transparent or (event.all_day and not all_day_events_block):
            continue
        start = max(day_start, event.start.astimezone(local_timezone) - buffer)
        end = min(day_end, event.end.astimezone(local_timezone) + buffer)
        if end > start:
            busy.append((start, end))
    busy.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    windows: list[FocusWindow] = []
    cursor = day_start
    for busy_start, busy_end in merged:
        if (busy_start - cursor).total_seconds() >= minimum_window_minutes * 60:
            windows.append(FocusWindow(cursor, busy_start))
        cursor = max(cursor, busy_end)
    if (day_end - cursor).total_seconds() >= minimum_window_minutes * 60:
        windows.append(FocusWindow(cursor, day_end))
    return windows


def schedule_tasks_into_windows(
    tasks: Iterable[Mapping[str, object]],
    windows: Iterable[FocusWindow],
) -> tuple[list[TaskTimeBlock], list[dict[str, object]]]:
    """Fit plan-order tasks into open windows, splitting only when necessary."""
    available = [[window.start, window.end] for window in windows]
    blocks: list[TaskTimeBlock] = []
    unscheduled: list[dict[str, object]] = []
    task_blocks: dict[str, list[int]] = {}

    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id") or f"task-{index}").strip()
        task_name = str(task.get("task_name") or "Planned task").strip()
        project_name = str(task.get("project_name") or "Unknown project").strip()
        try:
            remaining = int(task.get("estimated_minutes") or 25)
        except (TypeError, ValueError):
            remaining = 25
        remaining = min(1_440, max(1, remaining))
        original = remaining
        for window in available:
            if remaining <= 0:
                break
            start, end = window
            open_minutes = int((end - start).total_seconds() // 60)
            if open_minutes <= 0:
                continue
            minutes = min(remaining, open_minutes)
            block = TaskTimeBlock(
                task_id=task_id,
                task_name=task_name,
                project_name=project_name,
                start=start,
                end=start + timedelta(minutes=minutes),
                minutes=minutes,
            )
            task_blocks.setdefault(task_id, []).append(len(blocks))
            blocks.append(block)
            window[0] = block.end
            remaining -= minutes
        if remaining:
            unscheduled.append(
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "project_name": project_name,
                    "estimated_minutes": original,
                    "unscheduled_minutes": remaining,
                }
            )

    for indices in task_blocks.values():
        count = len(indices)
        for segment_index, block_index in enumerate(indices, start=1):
            blocks[block_index] = replace(
                blocks[block_index],
                segment_index=segment_index,
                segment_count=count,
            )
    return blocks, unscheduled
