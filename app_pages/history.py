from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from database.db import delete_focus_session, get_focus_sessions, update_focus_session
from database.models import SESSION_STATUSES
from services.analytics_service import parse_timestamp
from services.datetime_service import local_timezone_name
from services.timer_service import format_duration


st.title("Focus history")
st.caption(
    f"Times are shown in your local timezone ({local_timezone_name()}). "
    "Select a session to correct its details or remove test data."
)

st.session_state.setdefault("history_table_version", 0)


@st.dialog("Delete focus session")
def confirm_delete(session_id: int, task_name: str) -> None:
    st.warning(
        f"Delete the saved session for **{task_name}**? This cannot be undone.",
        icon=":material/warning:",
    )
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancel", key=f"cancel_delete_{session_id}"):
            st.rerun()
        if st.button(
            "Delete permanently",
            type="primary",
            icon=":material/delete:",
            key=f"confirm_delete_{session_id}",
        ):
            delete_focus_session(session_id)
            st.session_state.history_table_version += 1
            st.toast("Focus session deleted.", icon=":material/delete:")
            st.rerun()


sessions = get_focus_sessions()
if not sessions:
    st.info(
        "No focus sessions yet. Finish and save a session to see it here.",
        icon=":material/history:",
    )
    st.stop()

today = date.today()
with st.sidebar:
    st.subheader("History filters")
    start_date = st.date_input(
        "From", value=today - timedelta(days=30), max_value=today, key="history_from"
    )
    end_date = st.date_input(
        "Through", value=today, min_value=start_date, key="history_through"
    )
    project_options = sorted(
        {str(row.get("project_name") or "Unknown project") for row in sessions}
    )
    selected_projects = st.multiselect(
        "Projects", project_options, default=project_options, key="history_projects"
    )
    status_options = [status.title() for status in SESSION_STATUSES]
    selected_statuses = st.multiselect(
        "Outcomes", status_options, default=status_options, key="history_statuses"
    )

allowed_statuses = {status.lower() for status in selected_statuses}
filtered_sessions: list[dict[str, object]] = []
display_rows: list[dict[str, object]] = []
for row in sessions:
    local_started = parse_timestamp(row["started_at"])
    project_name = str(row.get("project_name") or "Unknown project")
    if not start_date <= local_started.date() <= end_date:
        continue
    if project_name not in selected_projects or row["status"] not in allowed_statuses:
        continue
    filtered_sessions.append(row)
    display_rows.append(
        {
            "Date and time": local_started,
            "Task": row["task_name"],
            "Project": project_name,
            "Planned": f"{row['planned_minutes']} min",
            "Focused": format_duration(int(row["actual_seconds"])),
            "Outcome": str(row["status"]).title(),
            "Notes": row["notes"],
        }
    )

if not display_rows:
    st.info("No sessions match these filters.", icon=":material/filter_list:")
    st.stop()

frame = pd.DataFrame(display_rows)
table_event = st.dataframe(
    frame,
    hide_index=True,
    key=f"history_table_{st.session_state.history_table_version}",
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Date and time": st.column_config.DatetimeColumn(
            "Date and time", format="MMM DD, YYYY · h:mm a", pinned=True
        ),
        "Task": st.column_config.TextColumn("Task", pinned=True),
    },
)
st.caption(
    f"Showing {len(display_rows)} of {len(sessions)} sessions. "
    "Select one row to edit or delete it."
)

selected_rows = table_event.selection.rows
if not selected_rows:
    st.stop()

selected = filtered_sessions[selected_rows[0]]
session_id = int(selected["id"])
local_started = parse_timestamp(selected["started_at"])
current_status = str(selected["status"])

with st.container(border=True):
    st.subheader("Edit selected session")
    st.caption(
        "Adjust Actual focus minutes when the timer kept running while you were away."
    )
    with st.form(f"edit_history_session_{session_id}"):
        task_name = st.text_input(
            "Task", value=str(selected["task_name"]), max_chars=500
        )
        project_name = st.text_input(
            "Project",
            value=str(selected.get("project_name") or "Unknown project"),
            max_chars=120,
        )
        edited_start = st.datetime_input(
            "Session start",
            value=local_started.replace(tzinfo=None),
            format="MM/DD/YYYY",
            step=60,
        )
        with st.container(horizontal=True):
            planned_minutes = int(
                st.number_input(
                    "Planned minutes",
                    min_value=1,
                    max_value=1_440,
                    value=int(selected["planned_minutes"]),
                )
            )
            actual_minutes = float(
                st.number_input(
                    "Actual focus minutes",
                    min_value=0.0,
                    max_value=10_080.0,
                    value=round(int(selected["actual_seconds"]) / 60, 1),
                    step=1.0,
                    format="%.1f",
                )
            )
        status = st.selectbox(
            "Outcome",
            list(SESSION_STATUSES),
            index=list(SESSION_STATUSES).index(current_status),
            format_func=str.title,
        )
        notes = st.text_area(
            "Notes", value=str(selected["notes"]), max_chars=500
        )
        update_clicked = st.form_submit_button(
            "Save corrections", type="primary", icon=":material/save:"
        )

    if update_clicked:
        if edited_start is None:
            st.error("Choose a session start time.")
        else:
            local_timezone = local_started.tzinfo or datetime.now().astimezone().tzinfo
            updated_start = edited_start.replace(tzinfo=local_timezone).astimezone(
                timezone.utc
            )
            try:
                update_focus_session(
                    session_id,
                    task_name=task_name,
                    project_name=project_name,
                    started_at=updated_start,
                    planned_minutes=planned_minutes,
                    actual_seconds=round(actual_minutes * 60),
                    status=status,
                    notes=notes,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.history_table_version += 1
                st.toast("Focus session updated.", icon=":material/check:")
                st.rerun()

    if st.button(
        "Delete this session",
        type="tertiary",
        icon=":material/delete:",
        key=f"delete_session_{session_id}",
    ):
        confirm_delete(session_id, str(selected["task_name"]))
