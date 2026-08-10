from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

import httpx
from todoist_api_python.api import TodoistAPI


class TodoistServiceError(RuntimeError):
    """A user-safe Todoist integration error."""


@dataclass(frozen=True, slots=True)
class TodoistProject:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TodoistTask:
    id: str
    content: str
    description: str
    project_id: str | None
    project_name: str
    section_id: str | None
    priority: int
    labels: tuple[str, ...]
    due_date: str | None
    due_datetime: str | None
    url: str | None
    due_string: str | None = None
    is_recurring: bool = False
    completed_at: datetime | None = None
    source: str = "todoist"

    @property
    def priority_label(self) -> str:
        return f"P{5 - self.priority}"

    def is_due_on(self, target_date: date) -> bool:
        return self.due_date == target_date.isoformat()


def _value(source: object, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _flatten_pages(pages: Iterable[object]) -> list[object]:
    flattened: list[object] = []
    for page in pages:
        if isinstance(page, (list, tuple)):
            flattened.extend(page)
        else:
            flattened.append(page)
    return flattened


def normalize_project(project: object) -> TodoistProject:
    return TodoistProject(id=str(_value(project, "id")), name=str(_value(project, "name")))


def normalize_task(
    task: object, project_names: Mapping[str, str] | None = None
) -> TodoistTask:
    task_id = str(_value(task, "id"))
    content = str(_value(task, "content", "Untitled task"))
    project_id_value = _value(task, "project_id")
    project_id = str(project_id_value) if project_id_value is not None else None
    project_name = (project_names or {}).get(project_id or "", "Unknown project")

    due = _value(task, "due")
    due_value = _value(due, "date") if due is not None else None
    due_date: str | None = None
    due_datetime: str | None = None
    due_string = str(_value(due, "string", "") or "") or None
    is_recurring = bool(
        _value(due, "is_recurring", _value(due, "recurring", False))
    )
    if isinstance(due_value, datetime):
        due_datetime = due_value.isoformat()
        due_date = due_value.date().isoformat()
    elif isinstance(due_value, date):
        due_date = due_value.isoformat()
    elif due_value:
        due_text = str(due_value)
        due_date = due_text[:10]
        if "T" in due_text:
            due_datetime = due_text

    task_url = _value(task, "url")
    if callable(task_url):
        task_url = task_url()

    completed_value = _value(task, "completed_at")
    completed_at: datetime | None = None
    if isinstance(completed_value, datetime):
        completed_at = completed_value
    elif completed_value:
        completed_at = datetime.fromisoformat(
            str(completed_value).replace("Z", "+00:00")
        )
    if completed_at is not None and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    return TodoistTask(
        id=task_id,
        content=content,
        description=str(_value(task, "description", "") or ""),
        project_id=project_id,
        project_name=project_name,
        section_id=(
            str(_value(task, "section_id"))
            if _value(task, "section_id") is not None
            else None
        ),
        priority=int(_value(task, "priority", 1) or 1),
        labels=tuple(_value(task, "labels", ()) or ()),
        due_date=due_date,
        due_datetime=due_datetime,
        url=str(task_url) if task_url else None,
        due_string=due_string,
        is_recurring=is_recurring,
        completed_at=completed_at,
    )


def normalize_completion_event(
    event: object, project_names: Mapping[str, str] | None = None
) -> TodoistTask:
    """Convert a Todoist Activity Log item completion into a task snapshot."""
    extra_data = _value(event, "extra_data", {}) or {}
    project_id_value = _value(event, "parent_project_id")
    due_date = _value(extra_data, "due_date")
    raw_task = {
        "id": _value(event, "object_id"),
        "content": _value(extra_data, "content", "Untitled task"),
        "description": _value(extra_data, "description", ""),
        "project_id": project_id_value,
        "section_id": _value(extra_data, "section_id"),
        "priority": _value(extra_data, "priority", 1),
        "labels": _value(extra_data, "labels", ()),
        "due": (
            {
                "date": due_date,
                "is_recurring": bool(_value(extra_data, "is_recurring", False)),
            }
            if due_date or _value(extra_data, "is_recurring", False)
            else None
        ),
        "completed_at": _value(event, "event_date"),
    }
    return normalize_task(raw_task, project_names)


class TodoistService:
    def __init__(
        self,
        token: str,
        api: TodoistAPI | None = None,
        activity_client: httpx.Client | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("A Todoist API token is required")
        self._token = token.strip()
        self._api = api or TodoistAPI(self._token)
        self._activity_client = activity_client

    def get_projects(self) -> list[TodoistProject]:
        try:
            projects = _flatten_pages(self._api.get_projects(limit=200))
            return [normalize_project(project) for project in projects]
        except Exception as exc:
            raise self._friendly_error(exc) from exc

    @staticmethod
    def project_name_map(projects: Iterable[TodoistProject]) -> dict[str, str]:
        return {project.id: project.name for project in projects}

    def get_active_tasks(
        self, project_names: Mapping[str, str] | None = None
    ) -> list[TodoistTask]:
        try:
            tasks = _flatten_pages(self._api.get_tasks(limit=200))
            return [normalize_task(task, project_names) for task in tasks]
        except Exception as exc:
            raise self._friendly_error(exc) from exc

    def get_tasks_due_today(
        self,
        project_names: Mapping[str, str] | None = None,
        *,
        today: date | None = None,
    ) -> list[TodoistTask]:
        target = today or date.today()
        return [
            task
            for task in self.get_active_tasks(project_names)
            if task.is_due_on(target)
        ]

    def get_completed_tasks(
        self,
        *,
        since: datetime,
        until: datetime,
        project_names: Mapping[str, str] | None = None,
    ) -> list[TodoistTask]:
        try:
            tasks = _flatten_pages(
                self._api.get_completed_tasks_by_completion_date(
                    since=since,
                    until=until,
                    limit=200,
                )
            )
            return [normalize_task(task, project_names) for task in tasks]
        except Exception as exc:
            raise self._friendly_error(exc) from exc

    def get_completed_task_events(
        self,
        *,
        since: datetime,
        until: datetime,
        project_names: Mapping[str, str] | None = None,
    ) -> list[TodoistTask]:
        """Read completions from Activity Log, including recurring occurrences."""
        client = self._activity_client or httpx.Client(timeout=20)
        should_close = self._activity_client is None
        completed: list[TodoistTask] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        try:
            while True:
                params: dict[str, str | int] = {
                    "object_type": "item",
                    "event_type": "completed",
                    "limit": 200,
                }
                if cursor:
                    params["cursor"] = cursor
                response = client.get(
                    "https://api.todoist.com/api/v1/activities",
                    headers={"Authorization": f"Bearer {self._token}"},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                page = [
                    normalize_completion_event(event, project_names)
                    for event in payload.get("results", [])
                    if _value(event, "object_id") is not None
                ]
                completed.extend(
                    task
                    for task in page
                    if task.completed_at is not None
                    and since <= task.completed_at <= until
                )

                # Activity events are newest-first. Once this page reaches the
                # requested boundary, older pages cannot contain useful events.
                if any(
                    task.completed_at is not None and task.completed_at < since
                    for task in page
                ):
                    break
                next_cursor = payload.get("next_cursor")
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = str(next_cursor)
            return completed
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        finally:
            if should_close:
                client.close()

    def create_recurring_task(
        self,
        content: str,
        *,
        due_string: str,
        project_id: str | None = None,
        project_names: Mapping[str, str] | None = None,
        priority: int = 1,
    ) -> TodoistTask:
        try:
            task = self._api.add_task(
                content.strip(),
                project_id=project_id,
                due_string=due_string.strip(),
                priority=priority,
            )
            normalized = normalize_task(task, project_names)
            if not normalized.is_recurring:
                raise TodoistServiceError(
                    "Todoist created the task, but its schedule is not recurring. "
                    "Edit the task in Todoist, then sync again."
                )
            return normalized
        except TodoistServiceError:
            raise
        except Exception as exc:
            raise self._friendly_error(exc) from exc

    def complete_task(self, task_id: str) -> None:
        try:
            if not self._api.complete_task(str(task_id)):
                raise TodoistServiceError("Todoist did not confirm task completion.")
        except TodoistServiceError:
            raise
        except Exception as exc:
            raise self._friendly_error(exc) from exc

    @staticmethod
    def _friendly_error(exc: Exception) -> TodoistServiceError:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                return TodoistServiceError(
                    "Todoist rejected the API token. Reconnect Todoist in Settings."
                )
            if status == 429:
                return TodoistServiceError(
                    "Todoist rate-limited the request. Wait briefly, then refresh."
                )
        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return TodoistServiceError(
                "Todoist is unreachable right now. Check your connection and try again."
            )
        return TodoistServiceError(
            "Todoist could not be loaded. Verify the token and try again."
        )
