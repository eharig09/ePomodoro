from __future__ import annotations

from datetime import date, datetime, time, timezone

import pandas as pd
import streamlit as st

from database.db import (
    get_active_local_focus_tasks,
    get_daily_plan,
    get_daily_ritual,
    get_focus_sessions,
    get_goal_links,
    get_goals,
    get_habit_daily_checkins,
    get_habit_definitions,
    get_task_preferences,
    mark_daily_startup_complete,
    record_sync_run,
    save_daily_plan,
    save_daily_shutdown,
    save_task_preferences,
    set_daily_plan_item_status,
)
from database.models import DailyPlan, TaskPreference
from services.productivity_service import (
    build_daily_plan_suggestion,
    build_estimation_calibration,
    calibrated_task_estimate,
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
st.session_state.setdefault("today_plan_suggestion", None)
st.session_state.setdefault("today_plan_editor_version", 0)


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
daily_ritual = get_daily_ritual(today)
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
goal_task_ids = {
    str(link["entity_id"])
    for link in goal_links
    if str(link["entity_type"]) == "task"
}
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

with st.container(border=True):
    st.subheader("Daily rhythm")
    with st.container(horizontal=True):
        if daily_ritual and daily_ritual.startup_completed_at:
            st.badge(
                "Startup complete",
                icon=":material/wb_sunny:",
                color="green",
            )
        else:
            st.badge(
                "Startup waiting",
                icon=":material/wb_sunny:",
                color="orange",
            )
        if daily_ritual and daily_ritual.shutdown_completed_at:
            st.badge(
                "Shutdown complete",
                icon=":material/nights_stay:",
                color="green",
            )
        else:
            st.badge(
                "Shutdown waiting",
                icon=":material/nights_stay:",
                color="gray",
            )
    if not daily_ritual or not daily_ritual.startup_completed_at:
        st.caption(
            "Saving today's plan completes the startup ritual. Choose capacity, "
            "an intention, and no more than three essential tasks."
        )

focus_sessions = get_focus_sessions()
estimation_calibration = build_estimation_calibration(focus_sessions)
suggestion = st.session_state.today_plan_suggestion
if (
    not isinstance(suggestion, dict)
    or suggestion.get("plan_date") != today.isoformat()
):
    suggestion = None
    st.session_state.today_plan_suggestion = None
suggested_items = suggestion.get("items", []) if suggestion else []
suggested_by_id = {
    str(item["task"].id): (index, item)
    for index, item in enumerate(suggested_items)
}


@st.dialog("Suggest my day")
def suggest_day_dialog() -> None:
    st.caption(
        "ePomodoro will rank active tasks, protect breathing room, and prepare an "
        "editable draft. Nothing is sent to Todoist."
    )
    with st.form("suggest_day_form"):
        suggested_energy = st.segmented_control(
            "Expected energy",
            ["low", "medium", "high"],
            default=plan.energy_level if plan else "medium",
            format_func=str.title,
        )
        suggested_available = int(
            st.number_input(
                "Available focus minutes",
                min_value=1,
                max_value=1_440,
                value=plan.available_minutes if plan else 240,
                step=15,
            )
        )
        buffer_percent = int(
            st.slider(
                "Breathing room",
                min_value=0,
                max_value=50,
                value=20,
                step=5,
                format="%d%%",
                help="Leaves capacity unplanned for interruptions and transitions.",
            )
        )
        maximum_tasks = int(
            st.number_input(
                "Maximum planned tasks",
                min_value=1,
                max_value=20,
                value=8,
            )
        )
        submitted = st.form_submit_button(
            "Build suggested plan",
            type="primary",
            icon=":material/auto_awesome:",
        )
    if submitted:
        if suggested_energy not in {"low", "medium", "high"}:
            st.error("Choose an expected energy level.")
            return
        result = build_daily_plan_suggestion(
            all_tasks,
            preferences=preferences,
            current_energy=str(suggested_energy),
            available_minutes=suggested_available,
            goal_task_ids=goal_task_ids,
            today=today,
            buffer_percent=buffer_percent,
            max_tasks=maximum_tasks,
            estimation_calibration=estimation_calibration,
        )
        st.session_state.today_plan_suggestion = {
            **result,
            "plan_date": today.isoformat(),
            "energy_level": str(suggested_energy),
        }
        st.session_state.today_plan_editor_version += 1
        st.rerun()


with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button(
        "Suggest my day",
        icon=":material/auto_awesome:",
        disabled=not all_tasks,
    ):
        suggest_day_dialog()

if suggestion:
    st.success(
        f"Suggested draft: {len(suggested_items)} tasks using "
        f"{suggestion['planned_minutes']} of {suggestion['usable_minutes']} usable minutes. "
        f"{suggestion['buffer_minutes']} minutes remain protected.",
        icon=":material/auto_awesome:",
    )
    if suggestion.get("unplanned_due"):
        due_names = ", ".join(
            str(item["task"].content)
            for item in suggestion["unplanned_due"][:3]
        )
        st.warning(
            f"Capacity could not fit every due task. Still unplanned: {due_names}.",
            icon=":material/warning:",
        )

default_energy = (
    str(suggestion["energy_level"])
    if suggestion
    else plan.energy_level
    if plan
    else "medium"
)
default_available = (
    int(suggestion["available_minutes"])
    if suggestion
    else plan.available_minutes
    if plan
    else 240
)
default_shutdown = (
    time.fromisoformat(plan.shutdown_time) if plan else time(hour=17)
)
default_intention = plan.intention if plan else ""

rows: list[dict[str, object]] = []
for index, task in enumerate(
    sorted(
        all_tasks,
        key=lambda item: (
            item.id not in (suggested_by_id if suggestion else saved_by_id),
            suggested_by_id.get(item.id, (10_000, None))[0]
            if suggestion
            else int(saved_by_id.get(item.id, {}).get("position", 10_000)),
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
    estimate_detail = calibrated_task_estimate(
        task, preference, estimation_calibration
    )
    suggested = suggested_by_id.get(task.id)
    include_default = (
        suggested is not None
        if suggestion
        else bool(saved)
        or (plan is None and (task.source == "local" or task.is_due_on(today)))
    )
    rows.append(
        {
            "Task ID": task.id,
            "Include": include_default,
            "Top 3": (
                bool(suggested and suggested[0] < 3)
                if suggestion
                else bool(saved and saved["is_top_three"])
            ),
            "Order": (
                suggested[0] + 1
                if suggested
                else int(saved["position"]) + 1
                if saved
                else index + 1
            ),
            "Task": task.content,
            "Project": task.project_name,
            "Priority": task.priority_label,
            "Estimate": task_estimate_minutes(task, preference),
            "Learned estimate": (
                f"{estimate_detail['estimated_minutes']} min"
                if estimate_detail["scope"] is not None
                else "Not enough history"
            ),
            "Evidence": (
                f"{str(estimate_detail['scope']).title()} Â· "
                f"{estimate_detail['samples']} sessions"
                if estimate_detail["scope"] is not None
                else "â€”"
            ),
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
        "Learned estimate",
        "Evidence",
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
        key=f"today_plan_editor_{st.session_state.today_plan_editor_version}",
        disabled=[
            "Task",
            "Project",
            "Priority",
            "Learned estimate",
            "Evidence",
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
            "Learned estimate": st.column_config.TextColumn("Learned time"),
            "Evidence": st.column_config.TextColumn("Estimate evidence"),
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
        mark_daily_startup_complete(today, completed_at=timestamp)
        st.session_state.today_plan_suggestion = None
        st.session_state.today_plan_editor_version += 1
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
    int(
        calibrated_task_estimate(
            task_by_id[task_id],
            preferences.get(task_id),
            estimation_calibration,
        )["estimated_minutes"]
    )
    for task_id in planned_ids
    if task_id in task_by_id
)
available = plan.available_minutes if plan else default_available
focused_today_minutes = round(
    sum(
        int(row.get("actual_seconds", 0) or 0)
        for row in focus_sessions
        if not bool(row.get("is_provisional"))
        and local_timestamp(row["started_at"]).date() == today
    )
    / 60
)
remaining_capacity = max(1, available - focused_today_minutes)

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

if focused_today_minutes:
    st.caption(
        f"{focused_today_minutes} focus minutes logged today; "
        f"about {remaining_capacity} remain in your stated capacity."
    )

active_plan_tasks = [
    task_by_id[task_id] for task_id in planned_ids if task_id in task_by_id
]
recommendation_pool = active_plan_tasks or all_tasks
recommendations = recommend_tasks(
    recommendation_pool,
    preferences=preferences,
    current_energy=plan.energy_level if plan else default_energy,
    available_minutes=remaining_capacity,
    planned_task_ids=planned_ids,
    top_task_ids=top_ids,
    goal_task_ids=goal_task_ids,
    today=today,
    estimation_calibration=estimation_calibration,
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
        if best["estimate_scope"] is not None:
            st.caption(
                f"Configured estimate: {best['base_estimated_minutes']} min. "
                f"Learned from {best['estimate_samples']} completed "
                f"{best['estimate_scope']} sessions."
            )
        st.write(" · ".join(str(reason) for reason in best["reasons"]))
        if st.button(
            "Focus on this task",
            type="primary",
            icon=":material/play_arrow:",
        ):
            st.session_state.selected_task_id = recommended_task.id
            st.switch_page("app_pages/focus.py")


@st.dialog("Daily shutdown", width="large")
def daily_shutdown_dialog() -> None:
    unfinished_items = [
        item for item in saved_items if str(item["status"]) == "planned"
    ]
    item_names = {
        str(item["task_id"]): str(item["task_name"])
        for item in unfinished_items
    }
    resolution_frame = pd.DataFrame(
        [
            {
                "Task ID": str(item["task_id"]),
                "Task": str(item["task_name"]),
                "Project": str(item["project_name"]),
                "Resolution": "Decide",
            }
            for item in unfinished_items
        ]
    )
    with st.form(f"daily_shutdown_{today.isoformat()}"):
        st.caption(
            "Resolve every unfinished task, capture what mattered, and choose the "
            "first task you want to see tomorrow."
        )
        st.caption(
            "These resolutions update your ePomodoro plan only; Todoist tasks are "
            "never completed or rescheduled from this shutdown."
        )
        if unfinished_items:
            edited_resolutions = st.data_editor(
                resolution_frame,
                hide_index=True,
                disabled=["Task", "Project"],
                column_config={
                    "Task ID": None,
                    "Task": st.column_config.TextColumn("Task", pinned=True),
                    "Resolution": st.column_config.SelectboxColumn(
                        "Resolution",
                        options=[
                            "Decide",
                            "Continue tomorrow",
                            "Defer",
                            "Completed",
                        ],
                        required=True,
                    ),
                },
            )
            first_task_id = st.selectbox(
                "First task tomorrow",
                [None, *item_names],
                format_func=lambda task_id: (
                    "No preference" if task_id is None else item_names[task_id]
                ),
            )
        else:
            edited_resolutions = resolution_frame
            first_task_id = None
            st.success(
                "There are no unfinished planned tasks to resolve.",
                icon=":material/task_alt:",
            )
        wins = st.text_area(
            "Wins",
            value=daily_ritual.wins if daily_ritual else "",
            max_chars=5_000,
            placeholder="What moved forward or went well?",
        )
        blockers = st.text_area(
            "Blockers",
            value=daily_ritual.blockers if daily_ritual else "",
            max_chars=5_000,
            placeholder="What got in the way or needs attention tomorrow?",
        )
        submitted = st.form_submit_button(
            "Finish shutdown",
            type="primary",
            icon=":material/nights_stay:",
        )
    if submitted:
        label_to_status = {
            "Continue tomorrow": "continue",
            "Defer": "deferred",
            "Completed": "completed",
        }
        rows = edited_resolutions.to_dict("records")
        resolutions = {
            str(row["Task ID"]): label_to_status.get(
                str(row["Resolution"]), "decide"
            )
            for row in rows
        }
        if first_task_id is not None:
            resolutions[str(first_task_id)] = "continue"
        if "decide" in resolutions.values():
            st.error("Choose a resolution for every unfinished task.")
            return
        save_daily_shutdown(
            today,
            resolutions=resolutions,
            wins=wins,
            blockers=blockers,
            tomorrow_first_task_id=(
                str(first_task_id) if first_task_id is not None else None
            ),
        )
        st.toast("Daily shutdown saved. Continued tasks are ready tomorrow.")
        st.rerun()


with st.container(border=True):
    st.subheader("Daily shutdown")
    if daily_ritual and daily_ritual.shutdown_completed_at:
        st.success("Today's shutdown is complete.", icon=":material/nights_stay:")
        if daily_ritual.tomorrow_first_task_name:
            st.caption(
                f"First task tomorrow: {daily_ritual.tomorrow_first_task_name}"
            )
        action_label = "Edit shutdown reflection"
        action_icon = ":material/edit:"
    else:
        unfinished_count = sum(
            str(item["status"]) == "planned" for item in saved_items
        )
        st.caption(
            f"{unfinished_count} unfinished planned task"
            f"{'s' if unfinished_count != 1 else ''} to resolve."
        )
        action_label = "Review and finish the day"
        action_icon = ":material/nights_stay:"
    if st.button(action_label, icon=action_icon, type="primary"):
        daily_shutdown_dialog()

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
