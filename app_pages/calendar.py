from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import sqlite3

import pandas as pd
import streamlit as st

from database.db import (
    get_app_setting,
    get_calendar_source_data,
    get_calendar_sources,
    get_daily_plan,
    get_task_preferences,
    save_calendar_source,
    set_app_setting,
)
from services.calendar_service import (
    CalendarEvent,
    CalendarServiceError,
    FocusWindow,
    build_focus_windows,
    count_calendar_events,
    fetch_calendar_ics,
    parse_calendar_events,
    round_up_datetime,
    schedule_tasks_into_windows,
)
from services.settings_service import get_calendar_feed_urls


def _saved_time(key: str, fallback: str) -> time:
    value = get_app_setting(key, fallback) or fallback
    try:
        return time.fromisoformat(value)
    except ValueError:
        return time.fromisoformat(fallback)


def _saved_int(key: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        value = int(get_app_setting(key, str(fallback)) or fallback)
    except ValueError:
        value = fallback
    return min(maximum, max(minimum, value))


def _clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _event_rows(
    events: list[CalendarEvent],
    *,
    all_day_events_block: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in events:
        rows.append(
            {
                "Start": "All day" if event.all_day else _clock(event.start),
                "End": "" if event.all_day else _clock(event.end),
                "Event": event.title,
                "Calendar": event.source_name,
                "Blocks focus": not event.transparent
                and (not event.all_day or all_day_events_block),
            }
        )
    return rows


st.title("Calendar plan")
st.caption(
    "Fit today's plan around real commitments. This view is read-only and never "
    "creates, moves, or deletes calendar events."
)

sources = get_calendar_sources()
calendar_urls = get_calendar_feed_urls()
with st.container(horizontal=True, horizontal_alignment="right"):
    refresh_clicked = st.button(
        "Refresh connected calendars",
        icon=":material/refresh:",
        disabled=not any(source.id in calendar_urls for source in sources),
    )
    if st.button("Add/manage calendars", icon=":material/settings:"):
        st.switch_page("app_pages/settings.py")

if refresh_clicked:
    refreshed = 0
    failures: list[str] = []
    with st.spinner("Refreshing read-only calendars..."):
        for source in sources:
            url = calendar_urls.get(source.id)
            if not url:
                continue
            try:
                ics_data = fetch_calendar_ics(url)
                timestamp = datetime.now(timezone.utc)
                save_calendar_source(
                    replace(
                        source,
                        event_count=count_calendar_events(ics_data),
                        last_refreshed_at=timestamp,
                        updated_at=timestamp,
                    ),
                    ics_data,
                )
                refreshed += 1
            except (CalendarServiceError, OSError, sqlite3.Error):
                failures.append(source.name)
    if failures:
        st.error(
            "Could not refresh: " + ", ".join(failures),
            icon=":material/cloud_off:",
        )
    if refreshed:
        st.toast(f"Refreshed {refreshed} calendar(s).", icon=":material/check:")
    if refreshed and not failures:
        st.rerun()

target_date = st.date_input("Plan date", value=date.today())
source_name_by_id = {source.id: source.name for source in sources}
if sources:
    selected_source_ids = st.pills(
        "Calendars to include",
        [source.id for source in sources],
        selection_mode="multi",
        default=[source.id for source in sources],
        format_func=lambda source_id: source_name_by_id[source_id],
        key="calendar_selected_sources",
        help="Busy time from every selected calendar is combined.",
    )
    included_source_ids = set(selected_source_ids or [])
else:
    included_source_ids = set()
local_timezone = datetime.now().astimezone().tzinfo
if local_timezone is None:  # pragma: no cover - every supported OS supplies one
    local_timezone = timezone.utc
current_time = datetime.now(local_timezone)
earliest_focus_time = (
    round_up_datetime(current_time, interval_minutes=5)
    if target_date == current_time.date()
    else None
)

saved_workday_start = _saved_time("calendar_workday_start", "08:00")
saved_workday_end = _saved_time("calendar_workday_end", "18:00")
saved_buffer = _saved_int("calendar_event_buffer", 10, 0, 120)
saved_minimum = _saved_int("calendar_minimum_window", 20, 5, 240)
saved_all_day = get_app_setting("calendar_all_day_blocks", "0") == "1"

with st.expander("Availability settings", icon=":material/tune:"):
    with st.form("calendar_availability_settings"):
        with st.container(horizontal=True):
            workday_start = st.time_input(
                "Day starts",
                value=saved_workday_start,
                step=timedelta(minutes=15),
            )
            workday_end = st.time_input(
                "Day ends",
                value=saved_workday_end,
                step=timedelta(minutes=15),
            )
            event_buffer = st.number_input(
                "Buffer around events",
                min_value=0,
                max_value=120,
                value=saved_buffer,
                step=5,
                help="Minutes protected before and after timed events.",
            )
            minimum_window = st.number_input(
                "Minimum focus window",
                min_value=5,
                max_value=240,
                value=saved_minimum,
                step=5,
            )
        all_day_blocks = st.toggle(
            "Treat all-day events as unavailable",
            value=saved_all_day,
        )
        save_defaults = st.form_submit_button(
            "Save availability defaults",
            icon=":material/save:",
        )
    if save_defaults:
        if workday_end <= workday_start:
            st.error("Day end must be after day start.")
        else:
            set_app_setting("calendar_workday_start", workday_start.isoformat())
            set_app_setting("calendar_workday_end", workday_end.isoformat())
            set_app_setting("calendar_event_buffer", str(int(event_buffer)))
            set_app_setting("calendar_minimum_window", str(int(minimum_window)))
            set_app_setting(
                "calendar_all_day_blocks",
                "1" if all_day_blocks else "0",
            )
            st.toast("Availability defaults saved.", icon=":material/check:")
            st.rerun()

if workday_end <= workday_start:
    st.error("Day end must be after day start.")
    st.stop()

range_start = datetime.combine(target_date, time.min, tzinfo=local_timezone)
range_end = range_start + timedelta(days=1)
events_by_source: dict[str, list[CalendarEvent]] = {
    source.id: [] for source in sources
}
source_errors: list[str] = []
for source in sources:
    ics_data = get_calendar_source_data(source.id)
    if not ics_data:
        continue
    try:
        events_by_source[source.id] = parse_calendar_events(
            ics_data,
            range_start=range_start,
            range_end=range_end,
            source_id=source.id,
            source_name=source.name,
            local_timezone=local_timezone,
        )
    except CalendarServiceError:
        source_errors.append(source.name)
events = [
    event
    for source_id, source_events in events_by_source.items()
    if source_id in included_source_ids
    for event in source_events
]
events.sort(key=lambda event: (event.start, event.end, event.title))
if source_errors:
    st.warning(
        "Some cached events could not be read: " + ", ".join(source_errors),
        icon=":material/warning:",
    )

if sources:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Included": source.id in included_source_ids,
                    "Calendar": source.name,
                    "Provider": source.provider.title(),
                    "Events on date": len(events_by_source[source.id]),
                    "Cached source events": source.event_count,
                    "Last refreshed": source.last_refreshed_at.astimezone(),
                }
                for source in sources
            ]
        ),
        hide_index=True,
        column_config={
            "Included": st.column_config.CheckboxColumn(),
            "Calendar": st.column_config.TextColumn(pinned=True),
            "Last refreshed": st.column_config.DatetimeColumn(
                format="MMM D, h:mm a"
            ),
        },
        key=f"calendar_source_status_{target_date.isoformat()}",
    )
    if not included_source_ids:
        st.warning(
            "Select at least one calendar to use calendar commitments.",
            icon=":material/calendar_month:",
        )

windows = build_focus_windows(
    events,
    target_date=target_date,
    workday_start=workday_start,
    workday_end=workday_end,
    local_timezone=local_timezone,
    event_buffer_minutes=int(event_buffer),
    minimum_window_minutes=int(minimum_window),
    all_day_events_block=all_day_blocks,
    not_before=earliest_focus_time,
)
plan, plan_items = get_daily_plan(target_date)
preferences = get_task_preferences()
task_rows: list[dict[str, object]] = []
for item in sorted(plan_items, key=lambda row: int(row["position"])):
    if str(item["status"]) != "planned":
        continue
    task_id = str(item["task_id"])
    preference = preferences.get(task_id)
    task_rows.append(
        {
            "task_id": task_id,
            "task_name": str(item["task_name"]),
            "project_name": str(item["project_name"]),
            "estimated_minutes": (
                preference.estimated_minutes if preference is not None else 25
            ),
        }
    )
blocks, unscheduled = schedule_tasks_into_windows(task_rows, windows)

open_minutes = sum(window.minutes for window in windows)
scheduled_minutes = sum(block.minutes for block in blocks)
blocking_events = sum(
    not event.transparent and (not event.all_day or all_day_blocks)
    for event in events
)
with st.container(horizontal=True):
    st.metric(
        "Open focus time",
        f"{open_minutes // 60}h {open_minutes % 60}m",
        border=True,
    )
    st.metric("Blocking events", blocking_events, border=True)
    st.metric(
        "Planned task time",
        f"{sum(int(row['estimated_minutes']) for row in task_rows)} min",
        border=True,
    )
    st.metric("Time placed", f"{scheduled_minutes} min", border=True)

if earliest_focus_time is not None:
    if earliest_focus_time.time() < workday_end:
        st.caption(
            f"Today's task blocks begin no earlier than {_clock(earliest_focus_time)}. "
            "Past workday time is excluded automatically."
        )
    else:
        st.caption(
            "The saved workday has ended, so no additional task blocks are suggested "
            "for today."
        )

if not sources:
    st.info(
        "No calendar is connected yet. The schedule below uses your saved workday as "
        "open time. Open Calendar connections to add Google, Outlook, or an ICS file.",
        icon=":material/calendar_add_on:",
    )

st.subheader("Calendar commitments")
if events:
    st.dataframe(
        pd.DataFrame(
            _event_rows(
                events,
                all_day_events_block=all_day_blocks,
            )
        ),
        hide_index=True,
        column_config={
            "Event": st.column_config.TextColumn(pinned=True),
            "Blocks focus": st.column_config.CheckboxColumn(),
        },
        key=f"calendar_events_{target_date.isoformat()}",
    )
else:
    st.caption("The selected calendars have no cached events on this date.")

st.subheader("Open focus windows")
if windows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Start": _clock(window.start),
                    "End": _clock(window.end),
                    "Available": window.minutes,
                }
                for window in windows
            ]
        ),
        hide_index=True,
        column_config={
            "Available": st.column_config.NumberColumn(format="%d min"),
        },
        key=f"calendar_windows_{target_date.isoformat()}",
    )
else:
    st.warning(
        "No focus window meets the current minimum. Shorten the buffer or minimum "
        "window, or protect a different part of the day.",
        icon=":material/event_busy:",
    )

st.subheader("Suggested task blocks")
st.caption(
    "Tasks follow the order in your saved daily plan. Long tasks may be split across "
    "windows. This preview does not write blocks to Google or Outlook."
)
if plan is None:
    st.info("Save a daily plan on Today to place tasks into these windows.")
elif blocks:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Start": _clock(block.start),
                    "End": _clock(block.end),
                    "Task": block.task_name,
                    "Project": block.project_name,
                    "Minutes": block.minutes,
                    "Part": (
                        f"{block.segment_index}/{block.segment_count}"
                        if block.segment_count > 1
                        else ""
                    ),
                }
                for block in blocks
            ]
        ),
        hide_index=True,
        column_config={
            "Task": st.column_config.TextColumn(pinned=True),
            "Minutes": st.column_config.NumberColumn(format="%d min"),
        },
        key=f"calendar_blocks_{target_date.isoformat()}",
    )
else:
    st.caption("There are no unfinished planned tasks to place.")

if unscheduled:
    st.warning(
        "Some task time does not fit inside the available windows.",
        icon=":material/schedule:",
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Task": row["task_name"],
                    "Project": row["project_name"],
                    "Still needs": row["unscheduled_minutes"],
                }
                for row in unscheduled
            ]
        ),
        hide_index=True,
        column_config={
            "Still needs": st.column_config.NumberColumn(format="%d min"),
        },
    )
