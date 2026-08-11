from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import sqlite3

import pandas as pd
import streamlit as st

from database.db import (
    create_habit_definition,
    get_daily_reflection,
    get_daily_reflections,
    get_habit_daily_checkins,
    get_habit_definitions,
    get_habit_group_icons,
    get_habit_label_links,
    get_habit_task_links,
    refresh_habit_task_link,
    record_habit_daily_checkin,
    record_sync_run,
    save_daily_reflection,
    save_habit_definition,
    save_habit_group_icons,
    set_habit_definition_active,
)
from services.cloud_account_service import (
    CloudAccountError,
    CloudConfigurationError,
    get_cloud_session,
)
from services.cloud_sync_service import synchronize_if_signed_in
from database.models import HabitDefinition
from services.habit_service import (
    best_streak,
    checkin_dates_by_habit,
    current_streak,
    record_task_completion,
    sync_completed_habit_history,
    task_link_from_todoist,
    tasks_matching_habit,
)
from services.datetime_service import local_timestamp
from services.settings_service import get_todoist_token
from services.todoist_service import (
    TodoistProject,
    TodoistService,
    TodoistServiceError,
    TodoistTask,
)


st.title("Habit tracker")
st.caption(
    "Create a habit with its own weekly schedule and link it to several Todoist "
    "tasks or labels. Completing any matching task counts for that day."
)

token = get_todoist_token()
today = date.today()
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MOOD_LABELS = {
    1: "😞 Rough",
    2: "😕 Low",
    3: "😐 Okay",
    4: "🙂 Good",
    5: "😄 Great",
}
MOOD_EMOJIS = {score: label.split()[0] for score, label in MOOD_LABELS.items()}


def sync_account_data() -> None:
    try:
        synchronize_if_signed_in()
        st.session_state.cloud_background_sync_error = None
    except (
        CloudAccountError,
        CloudConfigurationError,
        OSError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        st.session_state.cloud_background_sync_error = str(exc)
        st.toast(
            "Saved locally. Account sync will retry from Settings.",
            icon=":material/cloud_off:",
        )


def schedule_label(weekdays: tuple[int, ...]) -> str:
    if weekdays == tuple(range(7)):
        return "Every day"
    if weekdays == tuple(range(5)):
        return "Weekdays"
    return " · ".join(WEEKDAY_LABELS[weekday] for weekday in weekdays)


def habit_day_status(
    habit: HabitDefinition,
    completed_dates: set[date],
    day: date,
) -> str:
    created_on = local_timestamp(habit.created_at).date()
    if day < created_on:
        return "—"
    if day in completed_dates:
        return "✓"
    if day.weekday() not in habit.scheduled_weekdays:
        return "·"
    if day < today:
        return "✕"
    return "○"


def habit_calendar(
    habit: HabitDefinition,
    completed_dates: set[date],
    month_date: date,
    mood_by_date: dict[date, int],
) -> pd.DataFrame:
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        month_date.year, month_date.month
    )
    rows: list[dict[str, str]] = []
    for week_days in weeks:
        row: dict[str, str] = {}
        for weekday, day in enumerate(week_days):
            if day.month != month_date.month:
                row[WEEKDAY_LABELS[weekday]] = ""
                continue
            mood = MOOD_EMOJIS.get(mood_by_date.get(day, 0), "")
            status = habit_day_status(habit, completed_dates, day)
            row[WEEKDAY_LABELS[weekday]] = " ".join(
                part for part in (str(day.day), status, mood) if part
            )
        rows.append(row)
    return pd.DataFrame(rows)


def import_completed_checkins(tasks: list[TodoistTask]) -> None:
    for task in tasks:
        if task.completed_at is not None:
            record_task_completion(
                task,
                completed_at=task.completed_at,
                source="todoist",
            )


def sync_todoist_habits() -> None:
    if not token:
        st.session_state.habit_sync_error = (
            "Todoist is not connected. Local habits remain available."
        )
        st.session_state.habits_loaded = True
        return

    try:
        service = TodoistService(token)
        projects = service.get_projects()
        project_names = service.project_name_map(projects)
        tasks = service.get_active_tasks(project_names)
        now = datetime.now(timezone.utc)
        completed_tasks, matched_count = sync_completed_habit_history(
            token,
            now=now,
            days=89,
            service=service,
            project_names=project_names,
        )

        for task in tasks:
            refresh_habit_task_link(task_link_from_todoist(task))

        st.session_state.todoist_projects = projects
        st.session_state.todoist_tasks = tasks
        st.session_state.todoist_loaded = True
        st.session_state.todoist_error = None
        st.session_state.habit_completed_tasks = completed_tasks
        st.session_state.habit_sync_error = None
        st.session_state.habit_history_sync_error = None
        st.session_state.habit_history_checked = True
        record_sync_run(
            "habits",
            status="success",
            item_count=len(completed_tasks),
            matched_count=matched_count,
        )
    except TodoistServiceError as exc:
        st.session_state.habit_sync_error = str(exc)
        record_sync_run("habits", status="error", message=str(exc))
    finally:
        st.session_state.habits_loaded = True


def complete_matching_task(task: TodoistTask) -> None:
    try:
        TodoistService(token).complete_task(task.id)
    except TodoistServiceError as exc:
        st.error(str(exc))
        return

    matched = record_task_completion(
        task,
        completed_at=datetime.now(timezone.utc),
        source="habits",
    )
    st.session_state.habits_loaded = False
    st.session_state.todoist_loaded = False
    count = len(matched)
    st.toast(
        f"Todoist task completed · {count} habit{'s' if count != 1 else ''} updated.",
        icon=":material/check_circle:",
    )
    st.rerun()


def sorted_todoist_tasks() -> list[TodoistTask]:
    return sorted(
        st.session_state.todoist_tasks,
        key=lambda task: (
            task.project_name.casefold(),
            -task.priority,
            task.content.casefold(),
        ),
    )


@st.dialog("Habit rules", width="large")
def habit_rules_dialog(habit: HabitDefinition | None = None) -> None:
    tasks = sorted_todoist_tasks()
    task_by_id = {task.id: task for task in tasks}
    existing_links = get_habit_task_links(habit_id=habit.id) if habit else []
    existing_link_by_id = {link.todoist_task_id: link for link in existing_links}
    existing_labels = (
        get_habit_label_links(habit_id=habit.id).get(habit.id, set())
        if habit
        else set()
    )
    task_options = list(dict.fromkeys([*task_by_id, *existing_link_by_id]))
    selected_existing_ids = list(existing_link_by_id)
    available_labels = sorted(
        {
            *existing_labels,
            *(
                label
                for task in tasks
                for label in task.labels
            ),
        },
        key=str.casefold,
    )

    st.caption(
        "A day counts when any explicitly linked task is completed, or when any "
        "completed task has one of the selected Todoist labels."
    )
    with st.form(f"habit_rules_{habit.id if habit else 'new'}"):
        name = st.text_input(
            "Habit name",
            value=habit.name if habit else "",
            max_chars=300,
            placeholder="Learn something",
        )
        group_name = st.text_input(
            "Group",
            value=habit.group_name if habit else "Habits",
            max_chars=120,
        )
        scheduled_weekdays = st.pills(
            "Scheduled days",
            range(7),
            selection_mode="multi",
            default=list(habit.scheduled_weekdays if habit else range(7)),
            format_func=lambda weekday: WEEKDAY_LABELS[weekday],
            key=f"habit_schedule_{habit.id if habit else 'new'}",
            help="Only these Monday-to-Sunday scheduled days are required for the streak.",
        )
        labels = st.multiselect(
            "Todoist labels",
            available_labels,
            default=sorted(existing_labels),
            accept_new_options=True,
            help=(
                "Optional. Leave labels and tasks empty for a manual habit, or add a "
                "label so any matching Todoist completion counts."
            ),
        )
        selected_task_ids = st.multiselect(
            "Specific Todoist tasks",
            task_options,
            default=selected_existing_ids,
            format_func=lambda task_id: (
                f"{task_by_id[task_id].content} · {task_by_id[task_id].project_name}"
                if task_id in task_by_id
                else (
                    f"{existing_link_by_id[task_id].content} · "
                    f"{existing_link_by_id[task_id].project_name} · not active"
                )
            ),
        )
        st.caption(
            "No Todoist links creates a manual habit that you check off directly in ePomodoro."
        )
        submitted = st.form_submit_button(
            "Save habit",
            type="primary",
            icon=":material/save:",
        )

    if submitted:
        if not name.strip():
            st.error("Enter a habit name.")
            return
        if not scheduled_weekdays:
            st.error("Choose at least one scheduled day.")
            return
        selected_tasks = [
            task_by_id[task_id]
            for task_id in selected_task_ids
            if task_id in task_by_id
        ]
        if habit is None:
            saved = create_habit_definition(
                name,
                group_name=group_name,
                task_links=[task_link_from_todoist(task) for task in selected_tasks],
                labels=labels,
                scheduled_weekdays=scheduled_weekdays,
            )
        else:
            updated = HabitDefinition(
                id=habit.id,
                name=name,
                group_name=group_name,
                created_at=habit.created_at,
                updated_at=datetime.now(timezone.utc),
                scheduled_weekdays=tuple(sorted(scheduled_weekdays)),
                is_active=True,
            )
            save_habit_definition(
                updated,
                [
                    task_link_from_todoist(task, habit_id=habit.id)
                    for task in selected_tasks
                ]
                + [
                    existing_link_by_id[task_id]
                    for task_id in selected_task_ids
                    if task_id not in task_by_id
                ],
                labels,
            )
            saved = updated

        import_completed_checkins(st.session_state.habit_completed_tasks)
        sync_account_data()
        st.toast(f"{saved.name} saved.", icon=":material/check:")
        st.rerun()

    if habit is not None and st.button(
        "Stop tracking this habit",
        key=f"stop_habit_{habit.id}",
        icon=":material/remove_circle:",
        type="tertiary",
    ):
        set_habit_definition_active(habit.id, False)
        sync_account_data()
        st.toast("Habit removed from the tracker.", icon=":material/remove_circle:")
        st.rerun()


@st.dialog("Import recurring Todoist tasks", width="large")
def import_recurring_dialog() -> None:
    recurring = [task for task in sorted_todoist_tasks() if task.is_recurring]
    already_linked = {link.todoist_task_id for link in get_habit_task_links()}
    available = [task for task in recurring if task.id not in already_linked]
    if not available:
        st.info(
            "Every available recurring Todoist task is already linked to a habit.",
            icon=":material/check_circle:",
        )
        return
    task_by_id = {task.id: task for task in available}
    with st.form("import_recurring_habits"):
        selected_ids = st.multiselect(
            "Recurring tasks",
            list(task_by_id),
            format_func=lambda task_id: (
                f"{task_by_id[task_id].content} · "
                f"{task_by_id[task_id].project_name} · "
                f"{task_by_id[task_id].due_string or 'Recurring'}"
            ),
        )
        scheduled_weekdays = st.pills(
            "Habit streak days",
            range(7),
            selection_mode="multi",
            default=list(range(7)),
            format_func=lambda weekday: WEEKDAY_LABELS[weekday],
            key="import_habit_schedule",
            help="This Monday-to-Sunday schedule will apply to every selected habit.",
        )
        submitted = st.form_submit_button(
            "Import as habits",
            type="primary",
            icon=":material/download:",
        )
    if submitted:
        if not selected_ids or not scheduled_weekdays:
            st.error("Choose at least one task and one scheduled day.")
            return
        for task_id in selected_ids:
            task = task_by_id[task_id]
            create_habit_definition(
                task.content,
                group_name=task.project_name,
                task_links=[task_link_from_todoist(task)],
                scheduled_weekdays=scheduled_weekdays,
            )
        import_completed_checkins(st.session_state.habit_completed_tasks)
        sync_account_data()
        st.toast(
            f"Imported {len(selected_ids)} recurring habit{'s' if len(selected_ids) != 1 else ''}.",
            icon=":material/check:",
        )
        st.rerun()


@st.dialog("Create a recurring Todoist task")
def create_todoist_habit_dialog() -> None:
    projects: list[TodoistProject] = st.session_state.todoist_projects
    project_by_id = {project.id: project for project in projects}
    project_ids: list[str | None] = [None, *project_by_id]

    with st.form("create_todoist_habit"):
        content = st.text_input(
            "Task name",
            max_chars=300,
            placeholder="Stretch for five minutes",
        )
        due_string = st.text_input(
            "Recurring schedule",
            value="every day",
            max_chars=150,
            help="Use Todoist language such as every day, every weekday, or every Monday.",
        )
        scheduled_weekdays = st.pills(
            "Habit streak days",
            range(7),
            selection_mode="multi",
            default=list(range(7)),
            format_func=lambda weekday: WEEKDAY_LABELS[weekday],
            key="new_todoist_habit_schedule",
            help="Choose the Monday-to-Sunday days required for this habit's streak.",
        )
        project_id = st.selectbox(
            "Project",
            project_ids,
            format_func=lambda value: (
                "Inbox" if value is None else project_by_id[value].name
            ),
        )
        priority_label = st.selectbox("Priority", ["P1", "P2", "P3", "P4"])
        submitted = st.form_submit_button(
            "Create task and habit",
            type="primary",
            icon=":material/add_task:",
        )

    if submitted:
        if not content.strip() or not due_string.strip() or not scheduled_weekdays:
            st.error("Enter a task name, recurring schedule, and at least one streak day.")
            return
        project_names = TodoistService.project_name_map(projects)
        try:
            task = TodoistService(token).create_recurring_task(
                content,
                due_string=due_string,
                project_id=project_id,
                project_names=project_names,
                priority=5 - int(priority_label[1]),
            )
        except TodoistServiceError as exc:
            st.error(str(exc))
            return
        create_habit_definition(
            task.content,
            group_name=task.project_name,
            task_links=[task_link_from_todoist(task)],
            scheduled_weekdays=scheduled_weekdays,
        )
        sync_account_data()
        st.session_state.habits_loaded = False
        st.session_state.todoist_loaded = False
        st.toast("Todoist task and habit created.", icon=":material/check_circle:")
        st.rerun()


if not st.session_state.habits_loaded:
    with st.spinner("Syncing Todoist tasks and recent completions…"):
        sync_todoist_habits()

with st.container(horizontal=True, vertical_alignment="center"):
    if get_cloud_session() is not None:
        st.badge("Account sync on", icon=":material/cloud_done:", color="green")
    else:
        st.badge("Local only", icon=":material/cloud_off:", color="gray")
    if st.button(
        "Sync Todoist",
        icon=":material/sync:",
        disabled=not token,
    ):
        with st.spinner("Syncing Todoist habits…"):
            sync_todoist_habits()
        if st.session_state.habit_sync_error is None:
            st.toast("Todoist habits synced.", icon=":material/cloud_done:")
        st.rerun()
    if st.button(
        "New habit",
        icon=":material/add:",
        type="primary",
    ):
        habit_rules_dialog()
    if st.button(
        "Import recurring",
        icon=":material/event_repeat:",
        disabled=not token,
    ):
        import_recurring_dialog()
    if st.button(
        "Create Todoist task",
        icon=":material/add_task:",
        disabled=not token,
    ):
        create_todoist_habit_dialog()

if st.session_state.habit_sync_error:
    st.warning(st.session_state.habit_sync_error, icon=":material/cloud_off:")
elif st.session_state.habit_history_sync_error:
    st.warning(
        "Habit history could not be checked at launch. Use Sync Todoist to try again. "
        f"{st.session_state.habit_history_sync_error}",
        icon=":material/history_toggle_off:",
    )

habits = get_habit_definitions()
task_links = get_habit_task_links()
label_links = get_habit_label_links()
checkin_rows = get_habit_daily_checkins()
checkins_by_habit = checkin_dates_by_habit(checkin_rows)
week_start = today - timedelta(days=today.weekday())
week = [week_start + timedelta(days=offset) for offset in range(7)]
links_by_habit: defaultdict[str, list] = defaultdict(list)
for link in task_links:
    links_by_habit[link.habit_id].append(link)

scheduled_today = [habit for habit in habits if today.weekday() in habit.scheduled_weekdays]
done_today = sum(
    today in checkins_by_habit.get(habit.id, set()) for habit in scheduled_today
)
best_current_streak = max(
    (
        current_streak(
            checkins_by_habit.get(habit.id, set()),
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        )
        for habit in habits
    ),
    default=0,
)
best_ever_streak = max(
    (
        best_streak(
            checkins_by_habit.get(habit.id, set()),
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        )
        for habit in habits
    ),
    default=0,
)

metric_columns = st.columns(4)
with metric_columns[0].container(border=True):
    st.metric("Tracked habits", len(habits))
with metric_columns[1].container(border=True):
    st.metric("Scheduled today", f"{done_today}/{len(scheduled_today)}")
with metric_columns[2].container(border=True):
    st.metric("Best current streak", best_current_streak)
with metric_columns[3].container(border=True):
    st.metric("Best streak ever", best_ever_streak)

if not habits:
    st.info(
        "Create a habit and connect it to one or more Todoist labels or tasks.",
        icon=":material/label:",
    )
    st.stop()

group_names = sorted({habit.group_name for habit in habits}, key=str.casefold)
group_icons = get_habit_group_icons()
with st.popover("Group icons", icon=":material/add_reaction:"):
    st.caption("Assign one emoji or short symbol to each habit group.")
    icon_table = pd.DataFrame(
        {
            "Group": group_names,
            "Icon": [group_icons.get(group_name, "✨") for group_name in group_names],
        }
    )
    edited_icons = st.data_editor(
        icon_table,
        hide_index=True,
        disabled=["Group"],
        key="habit_group_icon_editor",
        column_config={
            "Group": st.column_config.TextColumn("Group", pinned=True),
            "Icon": st.column_config.TextColumn("Icon", max_chars=16),
        },
    )
    if st.button(
        "Save group icons",
        icon=":material/save:",
        type="primary",
        width="stretch",
    ):
        try:
            save_habit_group_icons(
                {
                    str(row["Group"]): str(row["Icon"])
                    for row in edited_icons.to_dict("records")
                }
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            sync_account_data()
            st.toast("Group icons saved.", icon=":material/check:")
            st.rerun()

st.subheader("Weekly plan")
st.caption("✓ completed · ✕ missed · ○ still available · · not scheduled")
status_rows: list[dict[str, object]] = []
for habit in habits:
    dates = checkins_by_habit.get(habit.id, set())
    row: dict[str, object] = {
        "Group": f"{group_icons.get(habit.group_name, '✨')} {habit.group_name}",
        "Habit": habit.name,
        "Schedule": schedule_label(habit.scheduled_weekdays),
        "Current": current_streak(
            dates,
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        ),
        "Best": best_streak(
            dates,
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        ),
    }
    for day in week:
        row[f"{WEEKDAY_LABELS[day.weekday()]} {day.day}"] = habit_day_status(
            habit, dates, day
        )
    status_rows.append(row)

st.dataframe(
    pd.DataFrame(status_rows),
    hide_index=True,
    column_config={
        "Group": st.column_config.TextColumn("Group", pinned=True),
        "Habit": st.column_config.TextColumn("Habit", pinned=True),
        "Current": st.column_config.NumberColumn("Current streak"),
        "Best": st.column_config.NumberColumn("Best streak"),
    },
)

st.subheader("Calendar")
with st.container(horizontal=True, vertical_alignment="bottom"):
    calendar_habit_id = st.selectbox(
        "Habit",
        [habit.id for habit in habits],
        format_func=lambda habit_id: next(
            habit.name for habit in habits if habit.id == habit_id
        ),
        key="habit_calendar_choice",
    )
    calendar_month = st.date_input(
        "Month containing",
        value=today,
        key="habit_calendar_month",
    )
calendar_habit = next(habit for habit in habits if habit.id == calendar_habit_id)
reflections = get_daily_reflections()
mood_by_date = {reflection.entry_date: reflection.mood for reflection in reflections}
st.caption("✓ completed · ✕ missed · ○ planned · · off-day · mood appears beside the day")
st.table(
    habit_calendar(
        calendar_habit,
        checkins_by_habit.get(calendar_habit.id, set()),
        calendar_month,
        mood_by_date,
    )
)

st.subheader("Mood and quick journal")
today_reflection = get_daily_reflection(today)
journal_prompts = {
    "Free write": "What is on your mind?",
    "Wins": "What went well today, even if it was small?",
    "Challenges": "What felt difficult, and what did you learn from it?",
    "Gratitude": "What are you grateful for today?",
    "Tomorrow": "What matters most tomorrow?",
}
journal_prompt = st.segmented_control(
    "Writing prompt",
    list(journal_prompts),
    default="Free write",
    key="journal_prompt",
)
with st.form("daily_reflection"):
    mood = st.pills(
        "How was today?",
        list(MOOD_LABELS),
        selection_mode="single",
        default=today_reflection.mood if today_reflection else None,
        format_func=lambda score: MOOD_LABELS[score],
    )
    journal = st.text_area(
        "Journal entry",
        value=today_reflection.journal if today_reflection else "",
        max_chars=10_000,
        placeholder=journal_prompts[str(journal_prompt or "Free write")],
        height=240,
        help="Up to 10,000 characters. Existing entries remain available below.",
    )
    reflection_submitted = st.form_submit_button(
        "Save reflection",
        icon=":material/bookmark:",
        type="primary",
    )
if reflection_submitted:
    if mood is None:
        st.error("Choose a mood before saving.")
    else:
        save_daily_reflection(today, mood=mood, journal=journal)
        sync_account_data()
        st.toast("Today's reflection saved.", icon=":material/check:")
        st.rerun()

if reflections:
    recent_reflections = reflections[:7]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": reflection.entry_date,
                    "Mood": MOOD_LABELS[reflection.mood],
                    "Journal": reflection.journal,
                }
                for reflection in recent_reflections
            ]
        ),
        hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn("Date", format="ddd, MMM D"),
            "Journal": st.column_config.TextColumn("Journal", width="large"),
        },
    )

st.subheader("Habit cards")
latest_today = {
    str(row["habit_id"]): row
    for row in checkin_rows
    if str(row["completed_on"]) == today.isoformat()
}

with st.container(horizontal=True, vertical_alignment="top", gap="small"):
    for habit in habits:
        dates = checkins_by_habit.get(habit.id, set())
        streak = current_streak(
            dates,
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        )
        longest_streak = best_streak(
            dates,
            today=today,
            scheduled_weekdays=habit.scheduled_weekdays,
        )
        completed_today = today in dates
        activity = " ".join(habit_day_status(habit, dates, day) for day in week)
        linked_tasks = links_by_habit.get(habit.id, [])
        labels = sorted(label_links.get(habit.id, set()))
        is_manual = not linked_tasks and not labels
        candidate_tasks = tasks_matching_habit(
            habit.id,
            st.session_state.todoist_tasks,
            task_links=task_links,
            label_links=label_links,
        )

        with st.container(border=True, width=320, gap="small"):
            st.markdown(f"**{habit.name}**")
            st.caption(habit.group_name)
            st.caption(f"Schedule · {schedule_label(habit.scheduled_weekdays)}")
            rule_parts = []
            if labels:
                rule_parts.append("Labels: " + ", ".join(f"@{label}" for label in labels))
            if linked_tasks:
                rule_parts.append(
                    f"{len(linked_tasks)} linked task{'s' if len(linked_tasks) != 1 else ''}"
                )
            st.caption(" · ".join(rule_parts))
            with st.container(horizontal=True):
                st.metric("Current streak", streak)
                st.metric("Best streak", longest_streak)
            st.caption(
                "This week · " + "  ".join(day.strftime("%a")[0] for day in week)
            )
            st.caption(activity)

            if today.weekday() not in habit.scheduled_weekdays:
                st.caption(
                    "Not scheduled today. An optional completion is recorded, but "
                    "does not replace a missed scheduled day."
                )

            if completed_today:
                completion = latest_today.get(habit.id, {})
                task_name = str(completion.get("todoist_task_name") or "").strip()
                message = f"Done today · {task_name}" if task_name else "Done today"
                st.success(message, icon=":material/check_circle:")
            elif is_manual:
                if st.button(
                    "Check in for today",
                    key=f"manual_habit_checkin_{habit.id}",
                    icon=":material/check_circle:",
                    type="primary",
                    width="stretch",
                ):
                    record_habit_daily_checkin(
                        habit.id,
                        datetime.now(timezone.utc),
                        source="habits",
                    )
                    sync_account_data()
                    st.toast(f"{habit.name} completed.", icon=":material/check:")
                    st.rerun()
            elif not candidate_tasks:
                st.caption(
                    "No currently active Todoist task matches these rules. A matching "
                    "completion found during sync will still count."
                )
            else:
                task_by_id = {task.id: task for task in candidate_tasks}
                if len(candidate_tasks) == 1:
                    selected_task = candidate_tasks[0]
                else:
                    selected_id = st.selectbox(
                        "Todoist task",
                        list(task_by_id),
                        key=f"habit_task_choice_{habit.id}",
                        format_func=lambda task_id: (
                            f"{task_by_id[task_id].content} · "
                            f"{task_by_id[task_id].project_name}"
                        ),
                    )
                    selected_task = task_by_id[selected_id]
                if st.button(
                    (
                        f"Complete · {selected_task.content}"
                        if len(candidate_tasks) == 1
                        else "Complete selected task"
                    ),
                    key=f"complete_habit_task_{habit.id}",
                    icon=":material/check:",
                    type="primary",
                    width="stretch",
                ):
                    complete_matching_task(selected_task)
                if selected_task.url:
                    st.link_button(
                        "Open selected task",
                        selected_task.url,
                        icon=":material/open_in_new:",
                        type="tertiary",
                        width="stretch",
                    )

            if st.button(
                "Edit rules",
                key=f"edit_habit_{habit.id}",
                icon=":material/edit:",
                type="tertiary",
                width="stretch",
            ):
                habit_rules_dialog(habit)
