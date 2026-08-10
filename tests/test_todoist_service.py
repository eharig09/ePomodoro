from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx

from services.todoist_service import (
    TodoistService,
    normalize_completion_event,
    normalize_task,
)


class FakeTodoistAPI:
    def __init__(self) -> None:
        self.completed: list[str] = []

    def get_projects(self, limit: int):
        assert limit == 200
        return iter([[SimpleNamespace(id="p1", name="Work")]])

    def get_tasks(self, limit: int):
        assert limit == 200
        return iter(
            [
                [
                    SimpleNamespace(
                        id="t1",
                        content="Plan launch",
                        description="Outline milestones",
                        project_id="p1",
                        section_id="s1",
                        priority=4,
                        labels=["planning"],
                        due=SimpleNamespace(date=date(2026, 8, 10)),
                        url="https://todoist.example/t1",
                    )
                ]
            ]
        )

    def complete_task(self, task_id: str) -> bool:
        self.completed.append(task_id)
        return True

    def get_completed_tasks_by_completion_date(
        self, *, since: datetime, until: datetime, limit: int
    ):
        assert since < until
        assert limit == 200
        return iter(
            [[
                SimpleNamespace(
                    id="t1",
                    content="Plan launch",
                    description="Outline milestones",
                    project_id="p1",
                    section_id="s1",
                    priority=4,
                    labels=["planning"],
                    due=SimpleNamespace(
                        date=date(2026, 8, 10),
                        string="every day",
                        is_recurring=True,
                    ),
                    completed_at=datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc),
                    url="https://todoist.example/t1",
                )
            ]]
        )

    def add_task(
        self,
        content: str,
        *,
        project_id: str | None,
        due_string: str,
        priority: int,
    ):
        return SimpleNamespace(
            id="new-habit",
            content=content,
            description="",
            project_id=project_id,
            section_id=None,
            priority=priority,
            labels=[],
            due=SimpleNamespace(
                date=date(2026, 8, 11),
                string=due_string,
                is_recurring=True,
            ),
            completed_at=None,
            url="https://todoist.example/new-habit",
        )


def test_normalize_task_keeps_snapshot_fields() -> None:
    raw = SimpleNamespace(
        id=99,
        content="Prepare slides",
        description="Use the new numbers",
        project_id=7,
        section_id=None,
        priority=2,
        labels=["presentation"],
        due=SimpleNamespace(date=datetime(2026, 8, 10, 9, 30)),
        url="https://todoist.example/99",
    )

    task = normalize_task(raw, {"7": "Client work"})

    assert task.id == "99"
    assert task.project_name == "Client work"
    assert task.due_date == "2026-08-10"
    assert task.due_datetime == "2026-08-10T09:30:00"
    assert task.labels == ("presentation",)


def test_normalize_task_keeps_recurring_and_completion_fields() -> None:
    completed_at = datetime(2026, 8, 10, 15, 30, tzinfo=timezone.utc)
    raw = SimpleNamespace(
        id="habit-1",
        content="Stretch",
        description="",
        project_id="p1",
        section_id=None,
        priority=1,
        labels=[],
        due=SimpleNamespace(
            date=date(2026, 8, 11), string="every day", is_recurring=True
        ),
        completed_at=completed_at,
        url="https://todoist.example/habit-1",
    )

    task = normalize_task(raw, {"p1": "Health"})

    assert task.is_recurring is True
    assert task.due_string == "every day"
    assert task.completed_at == completed_at


def test_normalize_completion_event_keeps_recurring_task_identity() -> None:
    task = normalize_completion_event(
        {
            "object_id": "habit-1",
            "parent_project_id": "p1",
            "event_date": "2026-08-10T16:20:35.238145Z",
            "extra_data": {
                "content": "Tactics and Calculation",
                "description": "Slow puzzles",
                "priority": 2,
                "labels": ["chess"],
                "due_date": "2026-08-17T13:00:00.000000Z",
                "is_recurring": True,
            },
        },
        {"p1": "Chess"},
    )

    assert task.id == "habit-1"
    assert task.project_name == "Chess"
    assert task.is_recurring is True
    assert task.labels == ("chess",)
    assert task.completed_at == datetime(
        2026, 8, 10, 16, 20, 35, 238145, tzinfo=timezone.utc
    )


def test_activity_history_includes_recurring_completion_events() -> None:
    responses = [
        {
            "results": [
                {
                    "object_id": "habit-1",
                    "parent_project_id": "p1",
                    "event_date": "2026-08-10T16:20:35Z",
                    "extra_data": {
                        "content": "Tactics and Calculation",
                        "priority": 2,
                        "is_recurring": True,
                    },
                },
                {
                    "object_id": "too-old",
                    "parent_project_id": "p1",
                    "event_date": "2026-07-01T12:00:00Z",
                    "extra_data": {"content": "Old task"},
                },
            ],
            "next_cursor": "unused-older-page",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.params["object_type"] == "item"
        assert request.url.params["event_type"] == "completed"
        return httpx.Response(200, json=responses.pop(0), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = TodoistService(
        "test-token", api=FakeTodoistAPI(), activity_client=client
    )
    completed = service.get_completed_task_events(
        since=datetime(2026, 8, 1, tzinfo=timezone.utc),
        until=datetime(2026, 8, 11, tzinfo=timezone.utc),
        project_names={"p1": "Chess"},
    )

    assert [task.id for task in completed] == ["habit-1"]
    assert completed[0].is_recurring is True
    client.close()


def test_service_flattens_sdk_pages_and_completes_tasks() -> None:
    api = FakeTodoistAPI()
    service = TodoistService("test-token", api=api)
    projects = service.get_projects()
    tasks = service.get_tasks_due_today(
        service.project_name_map(projects), today=date(2026, 8, 10)
    )

    assert [project.name for project in projects] == ["Work"]
    assert [task.content for task in tasks] == ["Plan launch"]
    service.complete_task("t1")
    assert api.completed == ["t1"]

    completed = service.get_completed_tasks(
        since=datetime(2026, 8, 1, tzinfo=timezone.utc),
        until=datetime(2026, 8, 11, tzinfo=timezone.utc),
        project_names={"p1": "Work"},
    )
    assert completed[0].completed_at == datetime(
        2026, 8, 10, 14, 0, tzinfo=timezone.utc
    )

    created = service.create_recurring_task(
        "Read",
        due_string="every day",
        project_id="p1",
        project_names={"p1": "Work"},
        priority=2,
    )
    assert created.id == "new-habit"
    assert created.is_recurring is True
