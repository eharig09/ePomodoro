from __future__ import annotations

from itertools import groupby
from typing import Iterable

import streamlit as st

from services.datetime_service import format_local_datetime
from services.todoist_service import TodoistTask


def _sort_tasks(tasks: Iterable[TodoistTask], sort_by: str) -> list[TodoistTask]:
    if sort_by == "Project":
        return sorted(
            tasks,
            key=lambda task: (
                task.project_name.casefold(),
                -task.priority,
                task.content.casefold(),
            ),
        )
    if sort_by == "Due date":
        return sorted(
            tasks,
            key=lambda task: (
                task.due_datetime or task.due_date or "9999-12-31",
                -task.priority,
                task.content.casefold(),
            ),
        )
    return sorted(
        tasks,
        key=lambda task: (
            -task.priority,
            task.due_datetime or task.due_date or "9999-12-31",
            task.content.casefold(),
        ),
    )


def _render_task(
    task: TodoistTask,
    selected_task_id: str | None,
    *,
    border: bool = True,
) -> bool:
    with st.container(border=border, gap=None):
        clicked = st.button(
            task.content,
            key=f"select_task_{task.id}",
            type="primary" if task.id == selected_task_id else "secondary",
            icon=(
                ":material/radio_button_checked:"
                if task.id == selected_task_id
                else None
            ),
            width="stretch",
        )
        details = f"{task.project_name} · {task.priority_label}"
        if task.due_datetime:
            details += f" · due {format_local_datetime(task.due_datetime)}"
        elif task.due_date:
            details += f" · due {task.due_date}"
        if task.source == "local":
            details += " · local"
        st.caption(details)
    return clicked


def render_task_list(
    tasks: list[TodoistTask],
    selected_task_id: str | None,
    *,
    sort_by: str = "Priority",
    group_by: str = "Project",
) -> str | None:
    if not tasks:
        st.info(
            "No tasks match this view. Add a local task or refresh Todoist.",
            icon=":material/task_alt:",
        )
        return None

    if group_by == "Priority":
        ordered = _sort_tasks(tasks, "Priority")
        key_function = lambda task: task.priority
        group_title = lambda priority: f"P{5 - priority} priority"
    elif group_by == "Project":
        ordered = _sort_tasks(tasks, "Project")
        key_function = lambda task: task.project_name
        group_title = str
    else:
        ordered = _sort_tasks(tasks, sort_by)
        key_function = None
        group_title = str

    selected: str | None = None
    if key_function is None:
        with st.container(height=440, border=False, gap="small"):
            for task in ordered:
                if _render_task(task, selected_task_id):
                    selected = task.id
        return selected

    task_groups = [
        (group, list(grouped_tasks))
        for group, grouped_tasks in groupby(ordered, key=key_function)
    ]
    with st.container(
        height=500,
        horizontal=True,
        vertical_alignment="top",
        gap="small",
        border=False,
    ):
        for group, grouped_tasks in task_groups:
            with st.container(border=True, width=300, gap="small"):
                st.markdown(f"**{group_title(group)}**")
                for task in grouped_tasks:
                    if _render_task(task, selected_task_id, border=False):
                        selected = task.id
    return selected
