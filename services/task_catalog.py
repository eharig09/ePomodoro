from __future__ import annotations

from database.models import LocalFocusTask
from services.todoist_service import TodoistProject, TodoistService, TodoistTask


def local_task_for_focus(task: LocalFocusTask) -> TodoistTask:
    return TodoistTask(
        id=f"local:{task.id}",
        content=task.content,
        description=task.description,
        project_id=None,
        project_name=task.project_name,
        section_id=None,
        priority=task.priority,
        labels=(),
        due_date=None,
        due_datetime=None,
        url=None,
        source="local",
    )


def load_todoist_catalog(token: str) -> tuple[list[TodoistProject], list[TodoistTask]]:
    service = TodoistService(token)
    projects = service.get_projects()
    project_names = service.project_name_map(projects)
    return projects, service.get_active_tasks(project_names)
