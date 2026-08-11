from __future__ import annotations

from datetime import date, datetime, time, timezone

import pandas as pd
import streamlit as st

from database.db import (
    get_active_local_focus_tasks,
    get_daily_plan,
    get_goal_links,
    get_goals,
    get_habit_daily_checkins,
    get_habit_definitions,
    get_task_preferences,
    record_sync_run,
    save_daily_plan,
    save_task_preferences,
    set_daily_plan_item_status,
)
from database.models import DailyPlan, TaskPreference
from services.productivity_service import (
    energy_level_from_labels,
    estimate_minutes_from_labels,
    recommend_tasks,
    task_energy_level,
    task_estimate_minutes,
)
from services.settings_service import get_todoist_token
from services.datetime_service import local_timestamp
from services.task_catalog import local_task_for_focus, load_todoist_catalog
from services.todoist_service import TodoistServiceError, TodoistTask


st.title("Today")
st.caption("Build a realistic plan, protect your top three, and choose the next right task.")

token = get_todoist_token()
today = date.today()


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


with st.container(horizontal=True, horizontal_alignment="right"):
    refresh_clicked = st.button(
        "Refresh Todoist",
        icon=":material/refresh:",
        disabled=not token,
    )

if refresh_clicked:
    st.session_state.todoist_loaded = False
if token and not st.session_state.todoist_loaded:
    with st.spinner("Loading today’s tasks…"):
        load_tasks()
if st.session_state.todoist_error:
    st.warning(st.session_state.todoist_error, icon=":material/cloud_off:")

todoist_tasks: list[TodoistTask] = st.session_state.todoist_tasks if token else []
local_tasks = [local_task_for_focus(task) for task in get_active_local_focus_tasks()]
all_tasks = [*todoist_tasks, *local_tasks]
task_by_id = {task.id: task for task in all_tasks}

plan, saved_items = get_daily_plan(today)
completed_today_ids = {
    task.id
    for task in st.session_state.habit_completed_tasks
    if task.completed_at is not None
    and local_timestamp(task.completed_at).date() == today
}
if completed_today_ids:
    for item in saved_items:
        if str(item["task_id"]) in completed_today_ids:
            set_daily_plan_item_status(today, str(item["task_id"]), "completed")
    plan, saved_items = get_daily_plan(today)
saved_by_id = {str(item["task_id"]): item for item in saved_items}
preferences = get_task_preferences()
goals = get_goals(active_only=True)
goal_by_id = {goal.id: goal for goal in goals}
goal_links = get_goal_links()
task_goal_names: dict[str, list[str]] = {}
for link in goal_links:
    if link["entity_type"] == "task" and link["goal_id"] in goal_by_id:
        task_goal_names.setdefault(link["entity_id"], []).append(
            goal_by_id[link["goal_id"]].name
        )

habits = get_habit_definitions()
today_habit_ids = {
    str(row["habit_id"])
    for row in get_habit_daily_checkins(since=today)
    if str(row["completed_on"]) == today.isoformat()
}
scheduled_habits = [
    habit for habit in habits if today.weekday() in habit.scheduled_weekdays
]

default_energy = plan.energy_level if plan else "medium"
default_available = plan.available_minutes if plan else 240
default_shutdown = (
    time.fromisoformat(plan.shutdown_time) if plan else time(hour=17)
)
default_intention = plan.intention if plan else ""

rows: list[dict[str, object]] = []
for index, task in enumerate(
    sorted(
        all_tasks,
        key=lambda item: (
            item.id not in saved_by_id,
            -item.priority,
            item.project_name.casefold(),
            item.content.casefold(),
        ),
    )
):
    saved = saved_by_id.get(task.id)
    preference = preferences.get(task.id)
    tagged_energy = energy_level_from_labels(task.labels)
    tagged_minutes = estimate_minutes_from_labels(task.labels)
    include_default = bool(saved) or (
        plan is None and (task.source == "local" or task.is_due_on(today))
    )
    rows.append(
        {
            "Task ID": task.id,
            "Include": include_default,
            "Top 3": bool(saved and saved["is_top_three"]),
            "Order": int(saved["position"]) + 1 if saved else index + 1,
            "Task": task.content,
            "Project": task.project_name,
            "Priority": task.priority_label,
            "Estimate": task_estimate_minutes(task, preference),
            "Estimate source": (
                "Todoist label"
                if tagged_minutes
                else "App setting"
                if preference
                else "Default"
            ),
            "Energy": task_energy_level(task, preference),
            "Energy source": (
                "Todoist label"
                if tagged_energy
                else "App setting"
                if preference
                else "Default"
            ),
            "Goal": ", ".join(task_goal_names.get(task.id, [])),
            "Source": task.source,
            "Status": str(saved["status"]) if saved else "planned",
        }
    )
plan_frame = pd.DataFrame(
    rows,
    columns=[
        "Task ID",
        "Include",
        "Top 3",
        "Order",
        "Task",
        "Project",
        "Priority",
        "Estimate",
        "Estimate source",
        "Energy",
        "Energy source",
        "Goal",
        "Source",
        "Status",
    ],
)

with st.form("daily_command_center"):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        energy_level = st.segmented_control(
            "Current energy",
            ["low", "medium", "high"],
            default=default_energy,
            format_func=str.title,
        )
        available_minutes = int(
            st.number_input(
                "Available focus minutes",
                min_value=1,
                max_value=1_440,
                value=default_available,
                step=15,
            )
        )
        shutdown_time = st.time_input("Shutdown time", value=default_shutdown)
    intention = st.text_input(
        "Daily intention",
        value=default_intention,
        max_chars=500,
        placeholder="What would make today feel successful?",
    )
    st.caption("Select tasks, estimate them, and mark no more than three as essential.")
    edited = st.data_editor(
        plan_frame,
        hide_index=True,
        key="today_plan_editor",
        disabled=[
            "Task",
            "Project",
            "Priority",
            "Estimate source",
            "Energy source",
            "Goal",
            "Source",
        ],
        column_config={
            "Task ID": None,
            "Include": st.column_config.CheckboxColumn("Plan"),
            "Top 3": st.column_config.CheckboxColumn("Top 3"),
            "Order": st.column_config.NumberColumn("Order", min_value=1, step=1),
            "Task": st.column_config.TextColumn("Task", pinned=True),
            "Estimate": st.column_config.NumberColumn(
                "Minutes", min_value=1, max_value=1_440, step=5
            ),
            "Estimate source": st.column_config.TextColumn("Time source"),
            "Energy": st.column_config.SelectboxColumn(
                "Energy", options=["low", "medium", "high"]
            ),
            "Energy source": st.column_config.TextColumn("Energy source"),
            "Status": st.column_config.SelectboxColumn(
                "Status", options=["planned", "completed", "deferred"]
            ),
        },
    )
    save_clicked = st.form_submit_button(
        "Save today’s plan",
        type="primary",
        icon=":material/save:",
    )
    st.caption(
        "Todoist labels energy_low, energy_medium, and energy_high (or low-energy, "
        "medium-energy, and high-energy) override app energy. Minute labels such as "
        "25min, 50_minutes, time_30, or 15 override the app estimate."
    )

if save_clicked:
    selected_rows = [row for row in edited.to_dict("records") if row["Include"]]
    top_count = sum(bool(row["Top 3"]) for row in selected_rows)
    if energy_level not in {"low", "medium", "high"}:
        st.error("Choose your current energy level.")
    elif top_count > 3:
        st.error("Choose no more than three top tasks.")
    else:
        timestamp = datetime.now(timezone.utc)
        save_task_preferences(
            [
                TaskPreference(
                    task_id=str(row["Task ID"]),
                    task_name=str(row["Task"]),
                    project_name=str(row["Project"]),
                    energy_level=str(row["Energy"]),
                    estimated_minutes=int(row["Estimate"]),
                    updated_at=timestamp,
                )
                for row in edited.to_dict("records")
            ]
        )
        daily_plan = DailyPlan(
            plan_date=today,
            energy_level=str(energy_level),
            available_minutes=available_minutes,
            shutdown_time=shutdown_time.strftime("%H:%M"),
            intention=intention,
            updated_at=timestamp,
        )
        save_daily_plan(
            daily_plan,
            [
                {
                    "task_id": row["Task ID"],
                    "task_name": row["Task"],
                    "project_name": row["Project"],
                    "source": row["Source"],
                    "position": int(row["Order"]) - 1,
                    "is_top_three": bool(row["Top 3"]),
                    "status": row["Status"],
                }
                for row in selected_rows
            ],
        )
        st.toast("Today’s plan saved.", icon=":material/check:")
        st.rerun()

plan, saved_items = get_daily_plan(today)
preferences = get_task_preferences()
planned_ids = {
    str(item["task_id"])
    for item in saved_items
    if str(item["status"]) == "planned"
}
top_ids = {
    str(item["task_id"])
    for item in saved_items
    if bool(item["is_top_three"]) and str(item["status"]) == "planned"
}
estimated_total = sum(
    preferences[task_id].estimated_minutes
    for task_id in planned_ids
    if task_id in preferences
)
available = plan.available_minutes if plan else default_available

with st.container(horizontal=True):
    st.metric("Planned", f"{estimated_total} min", border=True)
    st.metric("Available", f"{available} min", border=True)
    st.metric("Top tasks", f"{len(top_ids)}/3", border=True)
    st.metric(
        "Habits today",
        f"{sum(habit.id in today_habit_ids for habit in scheduled_habits)}/{len(scheduled_habits)}",
        border=True,
    )

if estimated_total > available:
    st.warning(
        f"The plan is {estimated_total - available} minutes over capacity. "
        "Defer something before the day decides for you.",
        icon=":material/warning:",
    )
elif saved_items:
    st.success(
        f"The plan leaves {available - estimated_total} minutes of breathing room.",
        icon=":material/check_circle:",
    )

active_plan_tasks = [task_by_id[task_id] for task_id in planned_ids if task_id in task_by_id]
recommendation_pool = active_plan_tasks or all_tasks
goal_task_ids = {
    str(link["entity_id"])
    for link in goal_links
    if str(link["entity_type"]) == "task"
}
recommendations = recommend_tasks(
    recommendation_pool,
    preferences=preferences,
    current_energy=plan.energy_level if plan else default_energy,
    available_minutes=available,
    planned_task_ids=planned_ids,
    top_task_ids=top_ids,
    goal_task_ids=goal_task_ids,
    today=today,
)

st.subheader("What should I do next?")
if not recommendations:
    st.info("Add an active task to receive a recommendation.", icon=":material/lightbulb:")
else:
    best = recommendations[0]
    recommended_task: TodoistTask = best["task"]
    with st.container(border=True):
        st.markdown(f"**{recommended_task.content}**")
        st.caption(
            f"{recommended_task.project_name} · {best['estimated_minutes']} min · "
            f"{str(best['energy_level']).title()} energy"
        )
        st.write(" · ".join(str(reason) for reason in best["reasons"]))
        if st.button(
            "Focus on this task",
            type="primary",
            icon=":material/play_arrow:",
        ):
            st.session_state.selected_task_id = recommended_task.id
            st.switch_page("app_pages/focus.py")

if scheduled_habits:
    st.subheader("Scheduled habits")
    habit_rows = [
        {
            "Habit": habit.name,
            "Group": habit.group_name,
            "Today": "✓ Done" if habit.id in today_habit_ids else "○ Planned",
        }
        for habit in scheduled_habits
    ]
    st.dataframe(pd.DataFrame(habit_rows), hide_index=True)
