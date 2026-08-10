from __future__ import annotations

from datetime import date

import streamlit as st

from database.db import (
    create_goal,
    delete_goal,
    get_active_local_focus_tasks,
    get_focus_sessions,
    get_goal_links,
    get_goals,
    get_habit_daily_checkins,
    get_habit_definitions,
    record_sync_run,
    save_goal_links,
    set_goal_status,
)
from services.productivity_service import calculate_goal_activity
from services.settings_service import get_todoist_token
from services.task_catalog import local_task_for_focus, load_todoist_catalog
from services.todoist_service import TodoistServiceError, TodoistTask


st.title("Goals")
st.caption("Connect daily tasks and habits to outcomes that matter.")

token = get_todoist_token()


def load_tasks() -> None:
    try:
        projects, tasks = load_todoist_catalog(token)
        st.session_state.todoist_projects = projects
        st.session_state.todoist_tasks = tasks
        st.session_state.todoist_error = None
        record_sync_run("active tasks", status="success", item_count=len(tasks))
    except TodoistServiceError as exc:
        st.session_state.todoist_error = str(exc)
        record_sync_run("active tasks", status="error", message=str(exc))
    finally:
        st.session_state.todoist_loaded = True


@st.dialog("Delete goal")
def confirm_delete(goal_id: str, goal_name: str) -> None:
    st.warning(
        f"Delete **{goal_name}** and its links? Your tasks, habits, and history remain.",
        icon=":material/warning:",
    )
    if st.button(
        "Delete goal",
        type="primary",
        icon=":material/delete:",
        width="stretch",
    ):
        delete_goal(goal_id)
        st.toast("Goal deleted.", icon=":material/delete:")
        st.rerun()


if token and not st.session_state.todoist_loaded:
    with st.spinner("Loading task choices…"):
        load_tasks()

todoist_tasks: list[TodoistTask] = st.session_state.todoist_tasks if token else []
local_tasks = [local_task_for_focus(task) for task in get_active_local_focus_tasks()]
tasks = [*todoist_tasks, *local_tasks]
habits = get_habit_definitions()

with st.expander("Create a goal", icon=":material/flag:"):
    with st.form("create_goal"):
        name = st.text_input(
            "Goal name", max_chars=200, placeholder="Build a consistent fitness routine"
        )
        description = st.text_area(
            "Why this matters", max_chars=1_000, height=100
        )
        use_target = st.checkbox("Add a target date")
        target_date = st.date_input("Target date", value=date.today())
        submitted = st.form_submit_button(
            "Create goal", type="primary", icon=":material/add:",
        )
    if submitted:
        try:
            created = create_goal(
                name,
                description=description,
                target_date=target_date if use_target else None,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.toast(f"{created.name} created.", icon=":material/check:")
            st.rerun()

goals = get_goals()
if not goals:
    st.info("Create your first goal, then connect tasks and habits to it.")
    st.stop()

links = get_goal_links()
activity = calculate_goal_activity(
    goals,
    links,
    get_focus_sessions(),
    get_habit_daily_checkins(),
)

with st.container(horizontal=True):
    st.metric("Active goals", sum(goal.status == "active" for goal in goals), border=True)
    st.metric(
        "Completed goals", sum(goal.status == "completed" for goal in goals), border=True
    )
    st.metric("Linked actions", len(links), border=True)

st.subheader("Goal momentum")
for goal in goals:
    metrics = activity[goal.id]
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.subheader(goal.name)
            st.badge(
                goal.status.title(),
                color=(
                    "green"
                    if goal.status == "completed"
                    else "orange"
                    if goal.status == "paused"
                    else "blue"
                ),
            )
        if goal.description:
            st.write(goal.description)
        details = []
        if goal.target_date:
            details.append(f"Target {goal.target_date.strftime('%b %d, %Y')}")
        if metrics["last_activity"]:
            details.append(f"Last activity {metrics['last_activity'].strftime('%b %d')}")
        st.caption(" · ".join(details) if details else "No target date")
        with st.container(horizontal=True):
            st.metric("Linked actions", metrics["linked_count"])
            st.metric("Focused", f"{int(metrics['focus_seconds']) / 3600:.1f}h")
            st.metric("Habit check-ins", metrics["habit_checkins"])

st.subheader("Connect actions")
selected_goal_id = st.selectbox(
    "Goal",
    [goal.id for goal in goals],
    format_func=lambda goal_id: next(goal.name for goal in goals if goal.id == goal_id),
)
selected_goal = next(goal for goal in goals if goal.id == selected_goal_id)
entity_names = {
    **{f"task:{task.id}": f"Task · {task.content} · {task.project_name}" for task in tasks},
    **{f"habit:{habit.id}": f"Habit · {habit.name} · {habit.group_name}" for habit in habits},
}
existing_keys = {
    f"{link['entity_type']}:{link['entity_id']}"
    for link in links
    if link["goal_id"] == selected_goal_id
}
options = list(dict.fromkeys([*entity_names, *existing_keys]))

with st.form(f"goal_links_{selected_goal_id}"):
    selected_entities = st.multiselect(
        "Tasks and habits",
        options,
        default=[key for key in options if key in existing_keys],
        format_func=lambda key: entity_names.get(key, f"Saved link · {key}"),
    )
    status = st.segmented_control(
        "Status",
        ["active", "paused", "completed"],
        default=selected_goal.status,
        format_func=str.title,
    )
    save_clicked = st.form_submit_button(
        "Save goal",
        type="primary",
        icon=":material/save:",
    )
if save_clicked:
    task_by_id = {task.id: task for task in tasks}
    habit_by_id = {habit.id: habit for habit in habits}
    saved_links: list[tuple[str, str, str]] = []
    for key in selected_entities:
        entity_type, entity_id = key.split(":", 1)
        if entity_type == "task" and entity_id in task_by_id:
            entity_name = task_by_id[entity_id].content
        elif entity_type == "habit" and entity_id in habit_by_id:
            entity_name = habit_by_id[entity_id].name
        else:
            entity_name = next(
                (
                    str(link["entity_name"])
                    for link in links
                    if link["goal_id"] == selected_goal_id
                    and link["entity_type"] == entity_type
                    and link["entity_id"] == entity_id
                ),
                entity_id,
            )
        saved_links.append((entity_type, entity_id, entity_name))
    save_goal_links(selected_goal_id, saved_links)
    set_goal_status(selected_goal_id, str(status))
    st.toast("Goal links saved.", icon=":material/check:")
    st.rerun()

if st.button(
    "Delete selected goal",
    type="tertiary",
    icon=":material/delete:",
):
    confirm_delete(selected_goal.id, selected_goal.name)
