from __future__ import annotations

from datetime import date, datetime, timezone

import streamlit as st

from components.session_summary import render_session_summary
from components.task_list import render_task_list
from components.timer import render_timer
from database.db import (
    complete_local_focus_task,
    create_local_focus_task,
    get_daily_plan,
    get_active_local_focus_tasks,
    get_task_preferences,
    record_sync_run,
    save_focus_session,
    set_daily_plan_item_status,
)
from database.models import FocusSessionCreate
from services.audio_service import completion_chime
from services.habit_service import record_task_completion
from services.productivity_service import (
    energy_level_from_labels,
    estimate_minutes_from_labels,
    task_energy_level,
    task_estimate_minutes,
)
from services.datetime_service import local_timestamp
from services.session_service import checkpoint_timer
from services.settings_service import get_todoist_token
from services.task_catalog import generic_focus_task, local_task_for_focus
from services.timer_service import (
    AWAITING_OUTCOME,
    TimerState,
    start_break_timer,
    start_timer,
)
from services.todoist_service import TodoistService, TodoistServiceError, TodoistTask


st.title("Focus")
st.caption("Choose one task, set a duration, and begin.")

token = get_todoist_token()


def load_todoist_data() -> None:
    try:
        service = TodoistService(token)
        projects = service.get_projects()
        project_names = service.project_name_map(projects)
        tasks = service.get_active_tasks(project_names)
        st.session_state.todoist_projects = projects
        st.session_state.todoist_tasks = tasks
        st.session_state.todoist_error = None
        record_sync_run("active tasks", status="success", item_count=len(tasks))
    except TodoistServiceError as exc:
        st.session_state.todoist_error = str(exc)
        record_sync_run("active tasks", status="error", message=str(exc))
    finally:
        st.session_state.todoist_loaded = True


def local_id(task: TodoistTask) -> str:
    return task.id.removeprefix("local:")


def render_current_task(task: TodoistTask) -> None:
    source_label = {
        "local": "Local focus task",
        "generic": "No linked task",
    }.get(task.source, "Todoist task")
    with st.container(border=True):
        st.caption(f"Current task · {source_label}")
        st.subheader(task.content)
        st.caption(f"{task.project_name} · {task.priority_label}")
        if task.description:
            st.write(task.description)
        if task.url:
            st.link_button(
                "Open in Todoist",
                task.url,
                icon=":material/open_in_new:",
                type="tertiary",
            )


def play_chime_once(state: TimerState) -> None:
    if state.sound_played:
        return
    if (
        state.completion_reason == "natural"
        and st.session_state.timer_sound_enabled
    ):
        st.audio(
            completion_chime(),
            format="audio/wav",
            autoplay=True,
            width=280,
        )
    state.sound_played = True


@st.dialog("Add a local focus task")
def add_local_task_dialog() -> None:
    st.caption("This task stays on this device and is never sent to Todoist.")
    with st.form("add_local_focus_task"):
        content = st.text_input(
            "Task name", max_chars=300, placeholder="Read a chapter"
        )
        description = st.text_area(
            "Description (optional)", max_chars=1_000, height=100
        )
        project_name = st.text_input(
            "Group or project", value="Local", max_chars=120
        )
        priority_label = st.selectbox("Priority", ["P1", "P2", "P3", "P4"])
        submitted = st.form_submit_button(
            "Add local task", type="primary", icon=":material/add_task:"
        )
    if submitted:
        if not content.strip():
            st.error("Enter a task name.")
            return
        create_local_focus_task(
            content,
            description=description,
            project_name=project_name,
            priority=5 - int(priority_label[1]),
        )
        st.rerun()


def render_break_launcher() -> None:
    with st.popover("Start a break", icon=":material/coffee:"):
        break_choice = st.segmented_control(
            "Break duration",
            ["5 min", "10 min", "15 min", "Custom"],
            default="5 min",
            key="break_duration_choice",
            persist_state="session",
        )
        if break_choice == "Custom":
            break_minutes = int(
                st.number_input(
                    "Custom break (minutes)",
                    min_value=1,
                    max_value=60,
                    value=5,
                    key="custom_break_minutes",
                    persist_state="session",
                )
            )
        else:
            break_minutes = int(str(break_choice).split()[0])
        if st.button(
            "Begin break",
            type="primary",
            icon=":material/play_arrow:",
            width="stretch",
        ):
            st.session_state.active_timer = start_break_timer(break_minutes)
            st.rerun()


def reset_timer() -> None:
    st.session_state.active_timer = None
    st.rerun()


active_timer: TimerState | None = st.session_state.active_timer

if active_timer is not None:
    if active_timer.timer_type == "break":
        with st.container(border=True):
            st.caption("Break timer")
            st.subheader("Step away and reset")
            st.caption("Breaks are not included in focus history or analytics.")
        if active_timer.phase == AWAITING_OUTCOME:
            play_chime_once(active_timer)
            message = (
                "Break complete."
                if active_timer.completion_reason == "natural"
                else "Break ended early."
            )
            st.success(message, icon=":material/coffee:")
            if st.button(
                "Return to tasks", type="primary", icon=":material/arrow_back:"
            ):
                reset_timer()
        else:
            render_timer(active_timer)
        st.stop()

    render_current_task(active_timer.task)

    if active_timer.phase == AWAITING_OUTCOME:
        play_chime_once(active_timer)
        if not active_timer.saved:
            submission = render_session_summary(active_timer)
            if submission.submitted:
                if not submission.status:
                    st.error("Choose a session outcome before saving.")
                else:
                    session = FocusSessionCreate(
                        session_uuid=active_timer.session_uuid,
                        todoist_task_id=active_timer.task.id,
                        task_name=active_timer.task.content,
                        project_id=active_timer.task.project_id,
                        project_name=active_timer.task.project_name,
                        started_at=active_timer.started_at,
                        ended_at=active_timer.ended_at or active_timer.started_at,
                        planned_minutes=active_timer.planned_minutes,
                        actual_seconds=active_timer.final_actual_seconds or 0,
                        status=submission.status,
                        notes=submission.notes,
                    )
                    save_focus_session(session)
                    if submission.status == "completed":
                        set_daily_plan_item_status(
                            local_timestamp(active_timer.started_at).date(),
                            active_timer.task.id,
                            "completed",
                        )
                    active_timer.saved = True
                    st.rerun()
        else:
            source = active_timer.task.source
            if active_timer.source_task_completed:
                completed_place = "Todoist" if source == "todoist" else "local tasks"
                st.success(
                    f"Focus session logged. The task was completed separately in {completed_place}.",
                    icon=":material/check_circle:",
                )
            elif source == "todoist":
                st.success(
                    "Focus session logged locally. No change was sent to Todoist; "
                    "the task is still active there.",
                    icon=":material/save:",
                )
            else:
                message = (
                    "Generic focus session logged."
                    if source == "generic"
                    else "Focus session logged locally. The local task remains active."
                )
                st.success(message, icon=":material/save:")

            with st.container(horizontal=True):
                if (
                    source == "todoist"
                    and token
                    and not active_timer.source_task_completed
                    and st.button(
                        "Complete in Todoist",
                        type="primary",
                        icon=":material/task_alt:",
                    )
                ):
                    try:
                        with st.spinner("Completing task in Todoist…"):
                            TodoistService(token).complete_task(active_timer.task.id)
                            matched_habits = record_task_completion(
                                active_timer.task,
                                completed_at=datetime.now(timezone.utc),
                                source="focus",
                            )
                            active_timer.source_task_completed = True
                            st.session_state.todoist_loaded = False
                            st.session_state.habits_loaded = False
                            load_todoist_data()
                        habit_note = (
                            f" {len(matched_habits)} habit"
                            f"{'s' if len(matched_habits) != 1 else ''} updated."
                            if matched_habits
                            else ""
                        )
                        st.toast(
                            f"Todoist task completed.{habit_note}",
                            icon=":material/check:",
                        )
                        st.rerun()
                    except TodoistServiceError as exc:
                        st.error(str(exc), icon=":material/error:")
                if (
                    source == "local"
                    and not active_timer.source_task_completed
                    and st.button(
                        "Complete local task",
                        type="primary",
                        icon=":material/task_alt:",
                    )
                ):
                    complete_local_focus_task(local_id(active_timer.task))
                    active_timer.source_task_completed = True
                    st.rerun()
                if st.button("Start another session", icon=":material/replay:"):
                    reset_timer()
    else:
        render_timer(active_timer)

    st.stop()

with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Generic focus", icon=":material/timer:"):
        st.session_state.selected_task_id = "generic:focus"
        st.rerun()
    if st.button("Add local task", icon=":material/add_task:"):
        add_local_task_dialog()
    render_break_launcher()
    refresh_clicked = st.button(
        "Refresh Todoist",
        icon=":material/refresh:",
        key="refresh_tasks",
        disabled=not token,
    )

if not token:
    st.info(
        "Todoist is not connected. Local focus tasks and break timers still work. "
        "Todoist is optional. Connect it in Settings to include Todoist tasks.",
        icon=":material/key:",
    )
else:
    if refresh_clicked:
        st.session_state.todoist_loaded = False
    if not st.session_state.todoist_loaded:
        with st.spinner("Loading Todoist tasks…"):
            load_todoist_data()
    if st.session_state.todoist_error:
        st.error(st.session_state.todoist_error, icon=":material/error:")
        if st.session_state.todoist_tasks:
            st.caption("Showing the last successfully loaded Todoist tasks.")

todoist_tasks: list[TodoistTask] = st.session_state.todoist_tasks if token else []
local_tasks = [local_task_for_focus(task) for task in get_active_local_focus_tasks()]
all_tasks = [*todoist_tasks, *local_tasks]

st.subheader("Tasks")
with st.container(horizontal=True, vertical_alignment="bottom"):
    view = st.segmented_control(
        "Task view",
        ["Today", "All active"],
        default="Today",
        key="focus_task_view",
        persist_state="session",
    )
    with st.popover("Organize", icon=":material/sort:"):
        sort_by = st.selectbox(
            "Sort by",
            ["Priority", "Project", "Due date"],
            key="focus_sort_by",
            persist_state="session",
        )
        group_by = st.selectbox(
            "Group by",
            ["None", "Priority", "Project"],
            key="focus_group_by",
            persist_state="session",
        )

if view == "Today":
    visible_todoist = [task for task in todoist_tasks if task.is_due_on(date.today())]
else:
    visible_todoist = todoist_tasks
visible_tasks = [*visible_todoist, *local_tasks]

st.caption(
    f"{len(visible_todoist)} Todoist task(s) · {len(local_tasks)} local task(s). "
    "Local tasks are always available in both views."
)

visible_ids = {task.id for task in visible_tasks}
visible_ids.add("generic:focus")
if st.session_state.selected_task_id not in visible_ids:
    st.session_state.selected_task_id = None

new_selection = render_task_list(
    visible_tasks,
    st.session_state.selected_task_id,
    sort_by=sort_by,
    group_by=group_by,
)
if new_selection is not None:
    st.session_state.selected_task_id = new_selection
    st.rerun()

task = next(
    (
        task
        for task in [generic_focus_task(), *visible_tasks]
        if task.id == st.session_state.selected_task_id
    ),
    None,
)
if task is None:
    st.caption("Select a task to configure a focus session.")
    st.stop()

render_current_task(task)

task_preference = get_task_preferences().get(task.id)
tagged_energy = energy_level_from_labels(task.labels)
tagged_minutes = estimate_minutes_from_labels(task.labels)
_, today_plan_items = get_daily_plan(date.today())
today_plan_item = next(
    (item for item in today_plan_items if str(item["task_id"]) == task.id),
    None,
)
if task_preference or tagged_energy or tagged_minutes:
    plan_note = (
        f"{task_estimate_minutes(task, task_preference)} min estimate · "
        f"{task_energy_level(task, task_preference).title()} energy"
    )
    if tagged_energy or tagged_minutes:
        plan_note += " · Todoist labels applied"
    if today_plan_item and bool(today_plan_item["is_top_three"]):
        plan_note += " · Today’s top 3"
    st.caption(plan_note)

if task.source == "local" and st.button(
    "Complete local task without a session",
    type="tertiary",
    icon=":material/task_alt:",
):
    complete_local_focus_task(local_id(task))
    st.session_state.selected_task_id = None
    st.rerun()

suggested_minutes = min(
    240, task_estimate_minutes(task, task_preference)
)
duration_choice = st.segmented_control(
    "Focus duration",
    [f"Suggested · {suggested_minutes} min", "15 min", "25 min", "50 min", "Custom"],
    default=f"Suggested · {suggested_minutes} min",
    key="focus_duration_choice",
    persist_state="session",
)
if duration_choice == "Custom":
    planned_minutes = int(
        st.number_input(
            "Custom duration (minutes)",
            min_value=1,
            max_value=240,
            value=25,
            step=5,
            key="focus_custom_minutes",
            persist_state="session",
        )
    )
else:
    planned_minutes = (
        suggested_minutes
        if str(duration_choice).startswith("Suggested")
        else int(str(duration_choice).split()[0])
    )

if st.button(
    "Start focus",
    type="primary",
    icon=":material/play_arrow:",
    width="stretch",
):
    if not 1 <= planned_minutes <= 240:
        st.error("Choose a duration between 1 and 240 minutes.")
    else:
        timer = start_timer(task, planned_minutes)
        checkpoint_timer(timer, force=True)
        st.session_state.active_timer = timer
        st.rerun()
