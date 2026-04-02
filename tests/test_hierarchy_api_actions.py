from __future__ import annotations

from fastapi.testclient import TestClient

from taskplane import hierarchy_api


def test_get_epic_story_tree_route_returns_tree_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_epic_story_tree",
        lambda connection, *, repo: {
            "repo": repo,
            "rows": [
                {
                    "epic_issue_number": 42,
                    "title": "Epic A",
                    "story_summaries": [],
                }
            ],
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/repos/codefromkarl/stardrifter/epic-story-tree")

    assert response.status_code == 200
    assert response.json()["rows"][0]["epic_issue_number"] == 42


def test_get_job_detail_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "get_job_detail",
        lambda connection, *, repo, job_id: {
            "repo": repo,
            "job": {"id": job_id, "job_kind": "story_decomposition"},
            "story": {},
            "task": {},
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/repos/codefromkarl/stardrifter/jobs/9")

    assert response.status_code == 200
    assert response.json()["job"]["id"] == 9


def test_post_epic_split_route_returns_action_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    monkeypatch.setattr(
        hierarchy_api,
        "run_epic_split_action",
        lambda *, repo, epic_issue_number: {
            "accepted": True,
            "action": "split_epic",
            "repo": repo,
            "epic_issue_number": epic_issue_number,
        },
    )

    response = client.post("/api/repos/codefromkarl/stardrifter/epics/42/split")

    assert response.status_code == 200
    assert response.json()["epic_issue_number"] == 42


def test_post_story_split_route_returns_action_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    monkeypatch.setattr(
        hierarchy_api,
        "run_story_split_action",
        lambda *, repo, story_issue_number: {
            "accepted": True,
            "action": "split_story",
            "repo": repo,
            "story_issue_number": story_issue_number,
        },
    )

    response = client.post("/api/repos/codefromkarl/stardrifter/stories/77/split")

    assert response.status_code == 200
    assert response.json()["story_issue_number"] == 77


def test_post_task_retry_route_maps_conflict_to_409(monkeypatch):
    client = TestClient(hierarchy_api.app)

    monkeypatch.setattr(
        hierarchy_api,
        "run_task_retry_action",
        lambda *, repo, work_id: (_ for _ in ()).throw(
            hierarchy_api.ConsoleActionConflictError("task is already running")
        ),
    )

    response = client.post("/api/repos/codefromkarl/stardrifter/tasks/task-1/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "task is already running"


def test_get_failed_notifications_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "get_failed_notifications",
        lambda connection, *, repo=None: {
            "notifications": [
                {
                    "id": 7,
                    "status": "failed",
                    "notification_type": "email",
                }
            ]
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/notifications/failed?limit=100")

    assert response.status_code == 200
    assert response.json()["notifications"][0]["id"] == 7


def test_get_agent_efficiency_stats_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "get_agent_efficiency_stats",
        lambda connection: {
            "stats": [
                {
                    "agent_name": "planner",
                    "total_executions": 12,
                    "success_rate_percent": 91,
                }
            ]
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/agents/stats")

    assert response.status_code == 200
    assert response.json()["stats"][0]["agent_name"] == "planner"


def test_get_executor_routing_profiles_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_executor_routing_profiles",
        lambda connection: {
            "profiles": [
                {
                    "id": 1,
                    "task_type": "core_path",
                    "priority": 300,
                }
            ]
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/executors/routing")

    assert response.status_code == 200
    assert response.json()["profiles"][0]["priority"] == 300


def test_get_executor_selection_events_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_executor_selection_events",
        lambda connection, *, repo, limit: {
            "repo": repo,
            "events": [
                {
                    "id": 9,
                    "executor_name": "codex",
                    "work_id": "task-1",
                }
            ],
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/repos/codefromkarl/stardrifter/executor-selections?limit=50")

    assert response.status_code == 200
    assert response.json()["events"][0]["executor_name"] == "codex"
