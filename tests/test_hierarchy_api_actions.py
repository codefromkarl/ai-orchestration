from __future__ import annotations

from fastapi.testclient import TestClient

from taskplane import actions_api_routes
from taskplane import governance_api_routes
from taskplane import hierarchy_api
from taskplane import hierarchy_issue_api_routes
from taskplane import intake_api_routes
from taskplane import observability_api_routes


def test_action_routes_are_reexported_from_dedicated_module():
    assert (
        hierarchy_api.post_repository_epic_split
        is actions_api_routes.post_repository_epic_split
    )
    assert (
        hierarchy_api.post_repository_story_split
        is actions_api_routes.post_repository_story_split
    )
    assert (
        hierarchy_api.post_repository_task_retry
        is actions_api_routes.post_repository_task_retry
    )


def test_intake_routes_are_reexported_from_dedicated_module():
    assert (
        hierarchy_api.get_natural_language_intents
        is intake_api_routes.get_natural_language_intents
    )
    assert (
        hierarchy_api.submit_natural_language_intent
        is intake_api_routes.submit_natural_language_intent
    )
    assert (
        hierarchy_api.answer_natural_language_intent
        is intake_api_routes.answer_natural_language_intent
    )
    assert (
        hierarchy_api.approve_natural_language_intent
        is intake_api_routes.approve_natural_language_intent
    )


def test_observability_routes_are_reexported_from_dedicated_module():
    assert (
        hierarchy_api.get_failed_notifications_route
        is observability_api_routes.get_failed_notifications_route
    )
    assert hierarchy_api.get_agent_status is observability_api_routes.get_agent_status
    assert (
        hierarchy_api.get_agent_efficiency_stats_route
        is observability_api_routes.get_agent_efficiency_stats_route
    )
    assert (
        hierarchy_api.executor_routing_profiles
        is observability_api_routes.executor_routing_profiles
    )


def test_hierarchy_and_issue_routes_are_reexported_from_dedicated_module():
    assert hierarchy_api.get_hierarchy is hierarchy_issue_api_routes.get_hierarchy
    assert hierarchy_api.get_issue is hierarchy_issue_api_routes.get_issue


def test_governance_routes_are_reexported_from_dedicated_module():
    assert hierarchy_api.get_governance_priority is governance_api_routes.get_governance_priority
    assert hierarchy_api.get_governance_health is governance_api_routes.get_governance_health
    assert hierarchy_api.resolve_governance_orphans is governance_api_routes.resolve_governance_orphans
    assert hierarchy_api.evaluate_auto_splits_endpoint is governance_api_routes.evaluate_auto_splits_endpoint
    assert hierarchy_api.run_governance_decisions is governance_api_routes.run_governance_decisions


def test_get_hierarchy_route_keeps_monkeypatch_compatibility(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "_load_issues",
        lambda conn, repo: [
            {
                "issue_number": 1,
                "title": "Epic A",
                "issue_kind": "epic",
                "github_state": "OPEN",
                "status_label": "todo",
                "url": "https://example.invalid/1",
                "lane": "Lane 01",
                "complexity": "medium",
                "explicit_parent_issue_numbers": [],
            },
            {
                "issue_number": 2,
                "title": "Story A",
                "issue_kind": "story",
                "github_state": "OPEN",
                "status_label": "todo",
                "url": "https://example.invalid/2",
                "lane": "Lane 01",
                "complexity": "medium",
                "explicit_parent_issue_numbers": [1],
            },
            {
                "issue_number": 3,
                "title": "Task A",
                "issue_kind": "task",
                "github_state": "OPEN",
                "status_label": "todo",
                "url": "https://example.invalid/3",
                "lane": "Lane 01",
                "complexity": "low",
                "explicit_parent_issue_numbers": [2],
            },
        ],
    )
    monkeypatch.setattr(
        hierarchy_api,
        "_load_work_items_by_issue",
        lambda conn, repo: {
            3: {
                "status": "ready",
                "blocked_reason": None,
                "decision_required": False,
            }
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/hierarchy?repo=codefromkarl/stardrifter")

    assert response.status_code == 200
    payload = response.json()
    assert payload["epics"][0]["issue_number"] == 1
    assert payload["epics"][0]["children"][0]["issue_number"] == 2
    assert payload["epics"][0]["children"][0]["children"][0]["issue_number"] == 3


def test_get_governance_priority_route_keeps_monkeypatch_compatibility(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        hierarchy_api._governance_priority_api,
        "load_priority_snapshot",
        lambda *, connection, repo: {"repo": repo, "tasks": [{"id": "task-1"}]},
    )
    monkeypatch.setattr(
        hierarchy_api._governance_priority_api,
        "build_api_response",
        lambda *, repo, snapshot, generated_at: {
            "repo": repo,
            "generated_at": generated_at,
            "tasks": snapshot["tasks"],
        },
    )

    response = client.get("/api/repos/codefromkarl/stardrifter/governance/priority")

    assert response.status_code == 200
    assert response.json()["repo"] == "codefromkarl/stardrifter"
    assert response.json()["tasks"][0]["id"] == "task-1"


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


def test_get_natural_language_intents_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_natural_language_intents",
        lambda connection, *, repo: {
            "repo": repo,
            "items": [
                {
                    "id": "intent-1",
                    "status": "awaiting_review",
                    "summary": "认证任务已完成拆分，等待人工审核。",
                }
            ],
        },
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/repos/codefromkarl/stardrifter/intents")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "intent-1"


def test_post_intent_submit_route_returns_intake_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeService:
        def submit_intent(self, *, repo: str, prompt: str):
            return type(
                "Intent",
                (),
                {
                    "id": "intent-1",
                    "repo": repo,
                    "status": "awaiting_review",
                    "summary": "已拆成两个 story，等待审批。",
                    "clarification_questions": (),
                    "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                    "promoted_epic_issue_number": None,
                    "approved_by": None,
                },
            )()

    monkeypatch.setattr(hierarchy_api, "_create_intake_service", lambda repository: FakeService())
    monkeypatch.setattr(hierarchy_api, "_build_intake_repository", lambda: object())

    response = client.post(
        "/api/repos/codefromkarl/stardrifter/intents",
        json={"prompt": "实现认证系统"},
    )

    assert response.status_code == 200
    assert response.json()["intent_id"] == "intent-1"
    assert response.json()["status"] == "awaiting_review"


def test_post_intent_answer_route_returns_updated_intake_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeService:
        def answer_intent(self, *, intent_id: str, answer: str):
            return type(
                "Intent",
                (),
                {
                    "id": intent_id,
                    "repo": "codefromkarl/stardrifter",
                    "status": "awaiting_review",
                    "summary": f"收到补充：{answer}",
                    "clarification_questions": (),
                    "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                    "promoted_epic_issue_number": None,
                    "approved_by": None,
                },
            )()

    monkeypatch.setattr(hierarchy_api, "_create_intake_service", lambda repository: FakeService())
    monkeypatch.setattr(hierarchy_api, "_build_intake_repository", lambda: object())

    response = client.post(
        "/api/intents/intent-1/answer",
        json={"answer": "使用 JWT"},
    )

    assert response.status_code == 200
    assert response.json()["intent_id"] == "intent-1"
    assert response.json()["summary"] == "收到补充：使用 JWT"


def test_post_intent_approve_route_returns_promoted_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeService:
        def approve_intent(self, *, intent_id: str, approver: str):
            return type(
                "Intent",
                (),
                {
                    "id": intent_id,
                    "repo": "codefromkarl/stardrifter",
                    "status": "promoted",
                    "summary": "已提升到任务池。",
                    "clarification_questions": (),
                    "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                    "promoted_epic_issue_number": 7001,
                    "approved_by": approver,
                },
            )()

    monkeypatch.setattr(hierarchy_api, "_create_intake_service", lambda repository: FakeService())
    monkeypatch.setattr(hierarchy_api, "_build_intake_repository", lambda: object())

    response = client.post(
        "/api/intents/intent-1/approve",
        json={"approver": "operator"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "promoted"
    assert response.json()["promoted_epic_issue_number"] == 7001


def test_post_intent_reject_route_returns_rejected_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeService:
        def reject_intent(self, *, intent_id: str, reviewer: str, reason: str):
            return type(
                "Intent",
                (),
                {
                    "id": intent_id,
                    "repo": "codefromkarl/stardrifter",
                    "status": "rejected",
                    "summary": "当前 proposal 已被拒绝。",
                    "clarification_questions": (),
                    "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                    "promoted_epic_issue_number": None,
                    "approved_by": None,
                    "reviewed_by": reviewer,
                    "review_action": "reject",
                    "review_feedback": reason,
                },
            )()

    monkeypatch.setattr(
        hierarchy_api, "_create_intake_service", lambda repository: FakeService()
    )
    monkeypatch.setattr(hierarchy_api, "_build_intake_repository", lambda: object())

    response = client.post(
        "/api/intents/intent-1/reject",
        json={"reviewer": "operator", "reason": "当前范围过大"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reviewed_by"] == "operator"
    assert response.json()["review_action"] == "reject"
    assert response.json()["review_feedback"] == "当前范围过大"


def test_post_intent_revise_route_returns_revised_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeService:
        def revise_intent(self, *, intent_id: str, reviewer: str, feedback: str):
            return type(
                "Intent",
                (),
                {
                    "id": intent_id,
                    "repo": "codefromkarl/stardrifter",
                    "status": "awaiting_clarification",
                    "summary": "已重新进入分析流程。",
                    "clarification_questions": ("请确认 MVP 边界。",),
                    "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                    "promoted_epic_issue_number": None,
                    "approved_by": None,
                    "reviewed_by": reviewer,
                    "review_action": "revise",
                    "review_feedback": feedback,
                },
            )()

    monkeypatch.setattr(
        hierarchy_api, "_create_intake_service", lambda repository: FakeService()
    )
    monkeypatch.setattr(hierarchy_api, "_build_intake_repository", lambda: object())

    response = client.post(
        "/api/intents/intent-1/revise",
        json={"reviewer": "operator", "feedback": "请补充 MVP 边界"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_clarification"
    assert response.json()["reviewed_by"] == "operator"
    assert response.json()["review_action"] == "revise"
    assert response.json()["review_feedback"] == "请补充 MVP 边界"


def test_post_operator_request_ack_route_returns_refresh_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    monkeypatch.setattr(
        hierarchy_api,
        "run_operator_request_ack_action",
        lambda *, repo, epic_issue_number, reason_code, closed_reason="acknowledged": {
            "accepted": True,
            "action": "ack_operator_request",
            "repo": repo,
            "epic_issue_number": epic_issue_number,
            "reason_code": reason_code,
            "closed_reason": closed_reason,
            "refresh": {"state": {"status": "active"}},
        },
    )

    response = client.post(
        "/api/repos/codefromkarl/stardrifter/epics/42/operator-requests/progress_timeout/ack"
    )

    assert response.status_code == 200
    assert response.json()["action"] == "ack_operator_request"
    assert response.json()["reason_code"] == "progress_timeout"
    assert response.json()["refresh"]["state"]["status"] == "active"


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

    response = client.get(
        "/api/repos/codefromkarl/stardrifter/executor-selections?limit=50"
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["executor_name"] == "codex"


def test_get_eval_work_items_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    observed: dict[str, object] = {}

    def _fake_list_work_items(
        connection, *, repo, after_work_id=None, limit=100, **kwargs
    ):
        observed["repo"] = repo
        observed["after_work_id"] = after_work_id
        observed["limit"] = limit
        return {
            "schema_version": "v1",
            "data": [{"kind": "work_snapshot", "work_id": "task-1"}],
            "page": {"next_cursor": None, "has_more": False},
        }

    monkeypatch.setattr(
        hierarchy_api,
        "list_work_snapshot_exports",
        _fake_list_work_items,
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get(
        "/api/eval/v1/repos/codefromkarl/stardrifter/work-items?after_work_id=task-0&limit=25"
    )

    assert response.status_code == 200
    assert observed == {
        "repo": "codefromkarl/stardrifter",
        "after_work_id": "task-0",
        "limit": 25,
    }
    assert response.json()["data"][0]["work_id"] == "task-1"


def test_get_eval_attempts_route_passes_cursor(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    observed: dict[str, object] = {}

    def _fake_list_attempts(
        connection, *, repo, after_run_id=None, limit=100, **kwargs
    ):
        observed["repo"] = repo
        observed["after_run_id"] = after_run_id
        observed["limit"] = limit
        return {
            "schema_version": "v1",
            "data": [{"kind": "execution_attempt", "run_id": 7}],
            "page": {"next_cursor": None, "has_more": False},
        }

    monkeypatch.setattr(
        hierarchy_api, "list_execution_attempt_exports", _fake_list_attempts
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get(
        "/api/eval/v1/repos/codefromkarl/stardrifter/attempts?after_run_id=5&limit=20"
    )

    assert response.status_code == 200
    assert observed == {
        "repo": "codefromkarl/stardrifter",
        "after_run_id": 5,
        "limit": 20,
    }
    assert response.json()["data"][0]["run_id"] == 7


def test_get_eval_verifications_route_passes_cursor(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    observed: dict[str, object] = {}

    def _fake_list_verifications(
        connection, *, repo, after_id=None, limit=100, **kwargs
    ):
        observed["repo"] = repo
        observed["after_id"] = after_id
        observed["limit"] = limit
        return {
            "schema_version": "v1",
            "data": [{"kind": "verification_result", "verification_id": "ver-7"}],
            "page": {"next_cursor": None, "has_more": False},
        }

    monkeypatch.setattr(
        hierarchy_api,
        "list_verification_result_exports",
        _fake_list_verifications,
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get(
        "/api/eval/v1/repos/codefromkarl/stardrifter/verifications?after_id=9&limit=15"
    )

    assert response.status_code == 200
    assert observed == {
        "repo": "codefromkarl/stardrifter",
        "after_id": 9,
        "limit": 15,
    }
    assert response.json()["data"][0]["verification_id"] == "ver-7"


def test_get_eval_work_items_route_returns_404_for_missing_repo(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_work_snapshot_exports",
        lambda connection, *, repo, limit=100, **kwargs: (_ for _ in ()).throw(
            hierarchy_api.ConsoleNotFoundError(f"repo {repo} not found")
        ),
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/eval/v1/repos/missing/repo/work-items")

    assert response.status_code == 404
    assert response.json()["detail"] == "repo missing/repo not found"


def test_get_eval_attempts_route_returns_404_for_missing_repo(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_execution_attempt_exports",
        lambda connection, *, repo, after_run_id=None, limit=100, **kwargs: (
            _ for _ in ()
        ).throw(hierarchy_api.ConsoleNotFoundError(f"repo {repo} not found")),
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/eval/v1/repos/missing/repo/attempts")

    assert response.status_code == 404
    assert response.json()["detail"] == "repo missing/repo not found"


def test_get_eval_verifications_route_returns_404_for_missing_repo(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "list_verification_result_exports",
        lambda connection, *, repo, after_id=None, limit=100, **kwargs: (
            _ for _ in ()
        ).throw(hierarchy_api.ConsoleNotFoundError(f"repo {repo} not found")),
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get("/api/eval/v1/repos/missing/repo/verifications")

    assert response.status_code == 404
    assert response.json()["detail"] == "repo missing/repo not found"


def test_get_eval_single_work_item_route_returns_payload(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "get_work_snapshot_export",
        lambda connection, *, repo, work_id: type(
            "Export",
            (),
            {"to_dict": lambda self: {"kind": "work_snapshot", "work_id": work_id}},
        )(),
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get(
        "/api/eval/v1/repos/codefromkarl/stardrifter/work-items/task-42"
    )

    assert response.status_code == 200
    assert response.json()["work_id"] == "task-42"


def test_get_eval_single_work_item_route_returns_404_when_missing(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "get_work_snapshot_export",
        lambda connection, *, repo, work_id: None,
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())

    response = client.get(
        "/api/eval/v1/repos/codefromkarl/stardrifter/work-items/task-404"
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "work item task-404 not found in codefromkarl/stardrifter"
    )
