from __future__ import annotations

from typing import Any, cast
from uuid import uuid4
from decimal import Decimal
from datetime import date, datetime

import psycopg
import pytest

from psycopg.rows import dict_row

from taskplane import console_api, hierarchy_api
from taskplane import _console_api_epics
from taskplane import _console_api_internal
from taskplane import _console_api_tasks
from taskplane import _console_api_repo_jobs
from taskplane import _console_api_stories
from taskplane.contextweaver_indexing import (
    CheckoutAliasRecord,
    FileIndexRegistry,
    IndexArtifactRecord,
)
from taskplane.console_read_api import (
    ConsoleNotFoundError,
    get_agent_efficiency_stats,
    get_epic_detail,
    get_job_detail,
    get_repo_summary,
    get_failed_notifications,
    get_story_detail,
    get_task_detail,
    list_executor_routing_profiles,
    list_executor_selection_events,
    list_runtime_observability,
    list_agent_status,
    list_ai_decisions,
    list_epic_rows,
    list_epic_story_tree,
    list_notifications,
    list_portfolio_summary,
)


def test_console_not_found_error_identity_is_preserved_across_public_aliases():
    assert ConsoleNotFoundError is console_api.ConsoleNotFoundError
    assert hierarchy_api.ConsoleNotFoundError is ConsoleNotFoundError


@pytest.mark.parametrize(
    "helper_name",
    [
        "_fetch_all",
        "_fetch_one",
        "_require_repo",
        "_rollback_if_possible",
        "_is_missing_epic_execution_state",
    ],
)
def test_console_helper_aliases_preserve_internal_identity(helper_name: str):
    assert getattr(console_api, helper_name) is getattr(
        _console_api_internal, helper_name
    )


def test_internal_require_repo_raises_public_console_not_found_error_identity():
    class FakeCursor:
        def execute(self, sql, params=None):
            return None

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    with pytest.raises(ConsoleNotFoundError) as exc_info:
        _console_api_internal._require_repo(FakeConnection(), "missing/repo")

    assert exc_info.type is ConsoleNotFoundError
    assert exc_info.type is console_api.ConsoleNotFoundError
    assert str(exc_info.value) == "repo missing/repo not found"


@pytest.mark.parametrize(
    "function_name",
    [
        "list_portfolio_summary",
        "list_ai_decisions",
        "list_notifications",
        "list_agent_status",
        "get_failed_notifications",
        "get_agent_efficiency_stats",
    ],
)
def test_portfolio_and_status_callables_preserve_public_identity(function_name: str):
    internal_callable = getattr(_console_api_internal, function_name)
    console_callable = getattr(console_api, function_name)
    hierarchy_callable = getattr(hierarchy_api, function_name)

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=[function_name],
            ),
            function_name,
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


def test_executor_routing_profiles_callable_preserves_public_identity():
    console_callable = console_api.list_executor_routing_profiles
    hierarchy_callable = hierarchy_api.list_executor_routing_profiles

    assert list_executor_routing_profiles is console_callable
    assert hierarchy_callable is console_callable


def test_executor_selection_events_callable_preserves_public_identity():
    console_callable = console_api.list_executor_selection_events
    hierarchy_callable = hierarchy_api.list_executor_selection_events

    assert list_executor_selection_events is console_callable
    assert hierarchy_callable is console_callable


@pytest.mark.parametrize(
    "function_name",
    [
        "get_repo_summary",
        "get_job_detail",
    ],
)
def test_repo_and_job_callables_preserve_public_identity(function_name: str):
    internal_callable = getattr(_console_api_repo_jobs, function_name)
    console_callable = getattr(console_api, function_name)
    hierarchy_callable = getattr(hierarchy_api, function_name)

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=[function_name],
            ),
            function_name,
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


@pytest.mark.parametrize(
    "function_name",
    [
        "list_epic_rows",
        "list_epic_story_tree",
        "get_epic_detail",
    ],
)
def test_epic_callables_preserve_public_identity(function_name: str):
    internal_callable = getattr(_console_api_epics, function_name)
    console_callable = getattr(console_api, function_name)
    hierarchy_callable = getattr(hierarchy_api, function_name)

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=[function_name],
            ),
            function_name,
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


def test_story_callable_preserves_public_identity():
    internal_callable = _console_api_stories.get_story_detail
    console_callable = console_api.get_story_detail
    hierarchy_callable = hierarchy_api.get_story_detail

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=["get_story_detail"],
            ),
            "get_story_detail",
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


def test_task_callable_preserves_public_identity():
    internal_callable = _console_api_tasks.get_task_detail
    console_callable = console_api.get_task_detail
    hierarchy_callable = hierarchy_api.get_task_detail

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=["get_task_detail"],
            ),
            "get_task_detail",
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


def test_runtime_observability_callable_preserves_public_identity():
    internal_callable = _console_api_tasks.list_runtime_observability
    console_callable = console_api.list_runtime_observability
    hierarchy_callable = hierarchy_api.list_runtime_observability

    assert console_callable is internal_callable
    assert (
        getattr(
            __import__(
                "taskplane.console_read_api",
                fromlist=["list_runtime_observability"],
            ),
            "list_runtime_observability",
        )
        is console_callable
    )
    assert hierarchy_callable is console_callable


@pytest.mark.parametrize(
    ("api_call", "expected_sql_fragment", "expected_params"),
    [
        (
            lambda connection: list_notifications(
                connection,
                repo="codefromkarl/stardrifter",
                include_sent=False,
                limit=25,
            ),
            "FROM v_pending_notifications_detailed\nWHERE repo = %s",
            ("codefromkarl/stardrifter", 25),
        ),
        (
            lambda connection: list_notifications(
                connection,
                repo="codefromkarl/stardrifter",
                include_sent=True,
                limit=25,
            ),
            "FROM v_notification_status\nWHERE repo = %s",
            ("codefromkarl/stardrifter", 25),
        ),
        (
            lambda connection: list_notifications(
                connection,
                include_sent=False,
                limit=25,
            ),
            "FROM v_pending_notifications_detailed",
            (25,),
        ),
        (
            lambda connection: list_notifications(
                connection,
                include_sent=True,
                limit=25,
            ),
            "FROM v_notification_status\nORDER BY created_at DESC",
            (25,),
        ),
    ],
)
def test_list_notifications_selects_expected_query_shape(
    api_call, expected_sql_fragment, expected_params
):
    executed: list[tuple[str, tuple[Any, ...] | None]] = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = api_call(FakeConnection())

    assert payload == {"notifications": []}
    assert len(executed) == 1
    sql, params = executed[0]
    assert expected_sql_fragment in sql
    assert params == expected_params


@pytest.mark.parametrize(
    "api_call",
    [
        list_portfolio_summary,
        list_ai_decisions,
        list_agent_status,
        get_failed_notifications,
        get_agent_efficiency_stats,
    ],
)
def test_console_read_apis_normalize_nested_decimal_and_datetime_values(api_call):
    row = {
        "ratio": Decimal("1.5"),
        "created_at": datetime(2026, 3, 25, 10, 11, 12),
        "milestones": [date(2026, 3, 26), Decimal("2.5")],
        "details": {
            "sent_at": datetime(2026, 3, 27, 8, 9, 10),
            "weights": (Decimal("3.5"), date(2026, 3, 28)),
        },
    }

    class FakeCursor:
        def execute(self, sql, params=None):
            return None

        def fetchall(self):
            return [row]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    if api_call is list_ai_decisions:
        payload = api_call(FakeConnection(), limit=10)
        key = "decisions"
    elif api_call is list_agent_status:
        payload = api_call(FakeConnection())
        key = "agents"
    elif api_call is get_failed_notifications:
        payload = api_call(FakeConnection())
        key = "notifications"
    elif api_call is get_agent_efficiency_stats:
        payload = api_call(FakeConnection())
        key = "stats"
    else:
        payload = api_call(FakeConnection())
        key = "repos"

    normalized = payload[key][0]
    assert normalized["ratio"] == 1.5
    assert normalized["created_at"] == "2026-03-25T10:11:12"
    assert normalized["milestones"] == ["2026-03-26", 2.5]
    assert normalized["details"] == {
        "sent_at": "2026-03-27T08:09:10",
        "weights": [3.5, "2026-03-28"],
    }


def test_get_epic_detail_includes_running_epic_decomposition_job():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM program_epic" in self.last_sql:
                return {
                    "issue_number": 42,
                    "repo": "codefromkarl/stardrifter",
                    "title": "Epic A",
                    "lane": "lane-1",
                    "program_status": "approved",
                    "execution_status": "planned",
                    "active_wave": "wave-1",
                    "notes": None,
                }
            if "FROM epic_execution_state" in self.last_sql:
                return None
            return None

        def fetchall(self):
            if "FROM program_story ps" in self.last_sql:
                return []
            if "FROM v_active_task_queue wi" in self.last_sql:
                return []
            if "FROM program_epic_dependency" in self.last_sql:
                return []
            if "FROM execution_job" in self.last_sql:
                return [
                    {
                        "id": 9,
                        "job_kind": "epic_decomposition",
                        "status": "running",
                        "story_issue_number": 42,
                        "worker_name": "console-epic-42",
                        "pid": 4242,
                        "command": "epic-command",
                        "log_path": "/tmp/epic.log",
                        "started_at": "2026-03-25T10:00:00+00:00",
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_epic_detail(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
        epic_issue_number=42,
    )

    assert len(payload["running_jobs"]) == 1
    assert payload["running_jobs"][0]["worker_name"] == "console-epic-42"


def test_list_epic_rows_exposes_epic_verification_fields():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "WHERE repo = %s" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            return [
                {
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 42,
                    "title": "Epic A",
                    "lane": "lane-1",
                    "program_status": "approved",
                    "execution_status": "gated",
                    "active_wave": "wave-1",
                    "notes": None,
                    "story_count": 2,
                    "task_count": 5,
                    "done_task_count": 5,
                    "blocked_task_count": 0,
                    "ready_task_count": 0,
                    "in_progress_task_count": 0,
                    "decision_required_task_count": 0,
                    "active_queue_task_count": 0,
                    "queued_story_decomposition_count": 0,
                    "queued_for_epic_decomposition": False,
                    "dependency_count": 0,
                    "running_job_count": 0,
                    "execution_state_status": "awaiting_operator",
                    "completed_story_count": 2,
                    "execution_state_blocked_story_count": 0,
                    "remaining_story_count": 0,
                    "verification_status": "failed",
                    "verification_reason_code": "epic_verification_failed",
                    "verification_summary": "epic regression failed",
                }
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = list_epic_rows(FakeConnection(), repo="codefromkarl/stardrifter")

    assert payload["rows"][0]["verification_status"] == "failed"
    assert payload["rows"][0]["verification_reason_code"] == "epic_verification_failed"
    assert payload["rows"][0]["verification_summary"] == "epic regression failed"


def test_get_story_detail_exposes_latest_story_verification_fields():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM program_story" in self.last_sql:
                return {
                    "issue_number": 29,
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 13,
                    "title": "Story 29",
                    "lane": "lane-1",
                    "complexity": "medium",
                    "program_status": "approved",
                    "execution_status": "gated",
                    "notes": None,
                    "verification_status": "failed",
                    "verification_summary": "story regression failed",
                    "verification_check_type": "pytest",
                }
            return None

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_story_detail(
        FakeConnection(), repo="codefromkarl/stardrifter", story_issue_number=29
    )

    assert payload["story"]["verification_status"] == "failed"
    assert payload["story"]["verification_summary"] == "story regression failed"
    assert payload["story"]["verification_check_type"] == "pytest"


def test_get_story_detail_normalizes_missing_decomposition_queue_as_empty_dict():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM program_story ps" in self.last_sql:
                return {
                    "story_issue_number": 21,
                    "epic_issue_number": 13,
                    "title": "Story A",
                    "lane": "lane-1",
                    "complexity": "medium",
                    "program_status": "approved",
                    "execution_status": "active",
                    "active_wave": "wave-1",
                    "notes": None,
                }
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return None
            return None

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_story_detail(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
        story_issue_number=21,
    )

    assert payload["story"]["story_issue_number"] == 21
    assert payload["decomposition_queue"] == {}


def test_get_task_detail_preserves_retry_context_payload_shape_through_public_facade():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM work_item wi" in self.last_sql:
                return {
                    "id": "issue-44",
                    "repo": "codefromkarl/stardrifter",
                    "story_issue_number": 21,
                    "epic_issue_number": 13,
                    "attempt_count": 2,
                    "last_failure_reason": "timeout",
                    "next_eligible_at": datetime(2026, 3, 28, 12, 30, 0),
                    "blocked_reason": "waiting_for_retry",
                    "decision_required": 0,
                }
            if "FROM work_claim wc" in self.last_sql:
                return None
            if "FROM github_issue_approval_event" in self.last_sql:
                return None
            if "FROM work_git_commit_link" in self.last_sql:
                return None
            return None

        def fetchall(self):
            if "FROM execution_run er" in self.last_sql:
                return [
                    {
                        "status": "done",
                        "summary": "latest summary",
                        "verification_passed": True,
                        "verification_output_digest": "verify-ok",
                        "result_payload_json": {
                            "reason_code": "ignored",
                            "outcome": "ignored",
                        },
                    },
                    {
                        "status": "failed",
                        "summary": "needs retry",
                        "verification_passed": False,
                        "verification_output_digest": "verify-fail",
                        "result_payload_json": {
                            "reason_code": "timeout",
                            "outcome": "retryable",
                            "nested": Decimal("2.5"),
                        },
                    },
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_task_detail(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
        work_id="issue-44",
    )

    assert payload["retry_context"] == {
        "attempt_count": 2,
        "last_failure_reason": "timeout",
        "next_eligible_at": "2026-03-28T12:30:00",
        "blocked_reason": "waiting_for_retry",
        "decision_required": False,
        "latest_run_status": "done",
        "latest_run_summary": "latest summary",
        "latest_failure_status": "failed",
        "latest_failure_summary": "needs retry",
        "latest_failure_reason_code": "timeout",
        "latest_failure_outcome": "retryable",
        "latest_failure_payload": {
            "reason_code": "timeout",
            "outcome": "retryable",
            "nested": 2.5,
        },
        "latest_verification_passed": False,
        "latest_verification_output_digest": "verify-fail",
    }


def test_get_task_detail_includes_repo_snapshot_state(monkeypatch):
    monkeypatch.setattr(
        _console_api_tasks,
        "get_repo_snapshot_health",
        lambda *, repo: {
            "status": "ready",
            "summary": "Ready and reusable.",
            "repository_id": f"control:{repo}",
            "snapshot_id": "abc123",
            "schema_version": "v1",
            "artifact_status": "ready",
            "artifact_age_seconds": 12.0,
            "lock_age_seconds": None,
            "lock_is_stale": False,
            "observed_at": "2026-03-30T10:00:00+00:00",
        },
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM work_item wi" in self.last_sql:
                return {"id": "issue-44", "repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_task_detail(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
        work_id="issue-44",
    )

    assert payload["snapshot_state"] == {
        "status": "ready",
        "summary": "Ready and reusable.",
        "repository_id": "control:codefromkarl/stardrifter",
        "snapshot_id": "abc123",
        "schema_version": "v1",
        "artifact_status": "ready",
        "artifact_age_seconds": 12.0,
        "lock_age_seconds": None,
        "lock_is_stale": False,
        "observed_at": "2026-03-30T10:00:00+00:00",
    }


def test_get_task_detail_includes_runtime_sessions_and_artifacts():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM work_item wi" in self.last_sql:
                return {"id": "issue-55", "repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            if "FROM execution_session es" in self.last_sql:
                return [
                    {
                        "id": "session-55",
                        "status": "active",
                        "attempt_index": 2,
                        "current_phase": "implementing",
                        "waiting_reason": None,
                        "created_at": datetime(2026, 4, 1, 10, 0, 0),
                        "updated_at": datetime(2026, 4, 1, 10, 5, 0),
                        "last_checkpoint_phase": "implementing",
                        "last_checkpoint_index": 3,
                        "last_checkpoint_summary": "synced resume context",
                        "last_checkpoint_next_action": "continue",
                    }
                ]
            if "FROM artifact" in self.last_sql:
                return [
                    {
                        "id": 77,
                        "session_id": "session-55",
                        "run_id": 12,
                        "artifact_type": "task_summary",
                        "artifact_key": "issue-55/task_summary/01.json",
                        "mime_type": "application/json",
                        "content_size_bytes": 321,
                        "metadata": {"summary": "captured runtime handoff"},
                        "created_at": datetime(2026, 4, 1, 10, 6, 0),
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_task_detail(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
        work_id="issue-55",
    )

    assert payload["sessions"] == [
        {
            "id": "session-55",
            "status": "active",
            "attempt_index": 2,
            "current_phase": "implementing",
            "waiting_reason": None,
            "created_at": "2026-04-01T10:00:00",
            "updated_at": "2026-04-01T10:05:00",
            "last_checkpoint_phase": "implementing",
            "last_checkpoint_index": 3,
            "last_checkpoint_summary": "synced resume context",
            "last_checkpoint_next_action": "continue",
        }
    ]
    assert payload["artifacts"] == [
        {
            "id": 77,
            "session_id": "session-55",
            "run_id": 12,
            "artifact_type": "task_summary",
            "artifact_key": "issue-55/task_summary/01.json",
            "mime_type": "application/json",
            "content_size_bytes": 321,
            "metadata": {"summary": "captured runtime handoff"},
            "created_at": "2026-04-01T10:06:00",
        }
    ]


def test_list_runtime_observability_returns_latest_session_and_artifact_summary():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            return {"repo": "codefromkarl/stardrifter"}

        def fetchall(self):
            if "FROM work_item wi" in self.last_sql:
                return [
                    {
                        "work_id": "issue-77",
                        "source_issue_number": 77,
                        "title": "runtime observation task",
                        "status": "in_progress",
                        "lane": "Lane 07",
                        "wave": "wave-7",
                        "blocked_reason": None,
                        "decision_required": False,
                        "last_failure_reason": "interrupted_retryable",
                        "active_claim_worker_name": "worker-7",
                        "session_id": "session-77",
                        "session_status": "active",
                        "session_attempt_index": 3,
                        "session_current_phase": "implementing",
                        "session_waiting_reason": None,
                        "session_updated_at": datetime(2026, 4, 1, 12, 30, 0),
                        "last_checkpoint_summary": "resume context refreshed",
                        "last_checkpoint_next_action": "continue",
                        "artifact_id": 701,
                        "artifact_session_id": "session-77",
                        "artifact_run_id": 33,
                        "artifact_type": "task_summary",
                        "artifact_key": "issue-77/task_summary/01.json",
                        "artifact_mime_type": "application/json",
                        "artifact_content_size_bytes": 512,
                        "artifact_metadata": {"summary": "captured latest planning state"},
                        "artifact_created_at": datetime(2026, 4, 1, 12, 31, 0),
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = list_runtime_observability(
        FakeConnection(),
        repo="codefromkarl/stardrifter",
    )

    assert payload == {
        "repo": "codefromkarl/stardrifter",
        "items": [
            {
                "work_id": "issue-77",
                "source_issue_number": 77,
                "title": "runtime observation task",
                "status": "in_progress",
                "lane": "Lane 07",
                "wave": "wave-7",
                "blocked_reason": None,
                "decision_required": False,
                "last_failure_reason": "interrupted_retryable",
                "active_claim_worker_name": "worker-7",
                "session_id": "session-77",
                "session_status": "active",
                "session_attempt_index": 3,
                "session_current_phase": "implementing",
                "session_waiting_reason": None,
                "session_updated_at": "2026-04-01T12:30:00",
                "last_checkpoint_summary": "resume context refreshed",
                "last_checkpoint_next_action": "continue",
                "artifact_id": 701,
                "artifact_session_id": "session-77",
                "artifact_run_id": 33,
                "artifact_type": "task_summary",
                "artifact_key": "issue-77/task_summary/01.json",
                "artifact_mime_type": "application/json",
                "artifact_content_size_bytes": 512,
                "artifact_metadata": {"summary": "captured latest planning state"},
                "artifact_created_at": "2026-04-01T12:31:00",
            }
        ],
    }


def test_get_repo_summary_formats_status_count_queries_with_real_table_name():
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchone(self):
            if "SELECT\n    %s AS repo" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter", "epic_count": 1}
            if "FROM (" in self.last_sql and "WHERE repo = %s" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            if "GROUP BY execution_status" in self.last_sql:
                return [{"status": "active", "count": 1}]
            if "GROUP BY status" in self.last_sql:
                return [{"status": "ready", "count": 2}]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_repo_summary(FakeConnection(), repo="codefromkarl/stardrifter")

    assert payload["epic_status_counts"][0]["status"] == "active"
    assert payload["story_status_counts"][0]["status"] == "active"
    assert payload["task_status_counts"][0]["status"] == "ready"
    assert any("FROM program_epic" in sql for sql in executed_sql)
    assert any("FROM program_story" in sql for sql in executed_sql)
    assert any("FROM work_item" in sql for sql in executed_sql)
    assert all("FROM {table}" not in sql for sql in executed_sql)


def test_get_repo_summary_includes_snapshot_health_from_registry(monkeypatch, tmp_path):
    registry_path = tmp_path / "registry.json"
    registry = FileIndexRegistry(registry_path)
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_REGISTRY_PATH", str(registry_path))
    registry.upsert_artifact(
        IndexArtifactRecord(
            repository_id="control:codefromkarl/stardrifter",
            snapshot_id="abc123",
            repo_root=str(tmp_path / "repo"),
            schema_version="v1",
            status="ready",
        )
    )
    registry.record_checkout_alias(
        CheckoutAliasRecord(
            checkout_path=str(tmp_path / "checkout-a"),
            repository_id="control:codefromkarl/stardrifter",
            snapshot_id="abc123",
            repo_root=str(tmp_path / "repo"),
        )
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "SELECT\n    %s AS repo" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter", "epic_count": 1}
            if "FROM (" in self.last_sql and "WHERE repo = %s" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_repo_summary(FakeConnection(), repo="codefromkarl/stardrifter")

    assert payload["snapshot_health"]["status"] == "ready"
    assert payload["snapshot_health"]["snapshot_id"] == "abc123"
    assert payload["snapshot_health"]["artifact_status"] == "ready"
    assert payload["snapshot_health"]["lock_is_stale"] is False


def test_list_epic_rows_falls_back_when_epic_execution_state_table_is_missing():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            if "epic_execution_state" in sql:
                raise psycopg.errors.UndefinedTable(
                    'relation "epic_execution_state" does not exist'
                )

        def fetchone(self):
            if "FROM (" in self.last_sql and "WHERE repo = %s" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            return [
                {
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 42,
                    "title": "Epic A",
                    "lane": "lane-1",
                    "program_status": "approved",
                    "execution_status": "planned",
                    "active_wave": "wave-1",
                    "notes": None,
                    "story_count": 2,
                    "task_count": 5,
                    "done_task_count": 3,
                    "blocked_task_count": 0,
                    "ready_task_count": 1,
                    "in_progress_task_count": 1,
                    "decision_required_task_count": 0,
                    "active_queue_task_count": 1,
                    "queued_story_decomposition_count": 0,
                    "queued_for_epic_decomposition": False,
                    "story_summaries": [
                        {
                            "story_issue_number": 101,
                            "title": "Story A",
                            "lane": "lane-1",
                            "complexity": "medium",
                            "execution_status": "active",
                            "program_status": "approved",
                            "active_wave": "wave-1",
                            "task_count": 3,
                            "done_task_count": 1,
                            "blocked_task_count": 0,
                            "ready_task_count": 1,
                            "in_progress_task_count": 1,
                            "decision_required_task_count": 0,
                            "active_queue_task_count": 1,
                            "running_job_count": 1,
                            "queued_for_story_decomposition": False,
                            "task_summaries": [
                                {
                                    "work_id": "issue-56",
                                    "source_issue_number": 56,
                                    "title": "Task A",
                                    "status": "done",
                                    "task_type": "documentation",
                                    "decision_required": False,
                                    "blocked_reason": None,
                                    "in_active_queue": False,
                                }
                            ],
                        }
                    ],
                    "dependency_count": 0,
                    "running_job_count": 1,
                    "execution_state_status": None,
                    "completed_story_count": 0,
                    "execution_state_blocked_story_count": 0,
                    "remaining_story_count": 0,
                }
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = list_epic_rows(FakeConnection(), repo="codefromkarl/stardrifter")

    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["epic_issue_number"] == 42
    assert payload["rows"][0]["execution_state_status"] is None
    assert "story_summaries" not in payload["rows"][0]


def test_list_epic_story_tree_returns_nested_story_and_task_summaries():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM (" in self.last_sql and "WHERE repo = %s" in self.last_sql:
                return {"repo": "codefromkarl/stardrifter"}
            return None

        def fetchall(self):
            return [
                {
                    "epic_issue_number": 42,
                    "title": "Epic A",
                    "story_summaries": [
                        {
                            "story_issue_number": 101,
                            "title": "Story A",
                            "lane": "lane-1",
                            "complexity": "medium",
                            "execution_status": "active",
                            "program_status": "approved",
                            "active_wave": "wave-1",
                            "task_count": 3,
                            "done_task_count": 1,
                            "blocked_task_count": 0,
                            "ready_task_count": 1,
                            "in_progress_task_count": 1,
                            "decision_required_task_count": 0,
                            "active_queue_task_count": 1,
                            "running_job_count": 1,
                            "queued_for_story_decomposition": False,
                            "task_summaries": [
                                {
                                    "work_id": "issue-56",
                                    "source_issue_number": 56,
                                    "title": "Task A",
                                    "status": "done",
                                    "task_type": "documentation",
                                    "decision_required": False,
                                    "blocked_reason": None,
                                    "in_active_queue": False,
                                }
                            ],
                        }
                    ],
                }
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = list_epic_story_tree(FakeConnection(), repo="codefromkarl/stardrifter")

    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["epic_issue_number"] == 42
    assert payload["rows"][0]["story_summaries"][0]["story_issue_number"] == 101
    assert (
        payload["rows"][0]["story_summaries"][0]["task_summaries"][0]["work_id"]
        == "issue-56"
    )


def test_get_job_detail_returns_job_with_story_and_task_context():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM execution_job" in self.last_sql:
                return {
                    "id": 9,
                    "repo": "codefromkarl/stardrifter",
                    "job_kind": "story_decomposition",
                    "status": "running",
                    "story_issue_number": 21,
                    "work_id": "issue-44",
                    "launch_backend": "console",
                    "worker_name": "console-story-21",
                    "pid": 4242,
                    "command": "story-command",
                    "log_path": "/tmp/story-21.log",
                    "started_at": "2026-03-25T10:00:00+00:00",
                    "finished_at": None,
                    "exit_code": None,
                }
            if "FROM program_story ps" in self.last_sql:
                return {
                    "story_issue_number": 21,
                    "story_title": "Story A",
                    "story_execution_status": "active",
                    "epic_issue_number": 13,
                    "epic_title": "Epic A",
                    "epic_execution_status": "active",
                }
            if "FROM work_item wi" in self.last_sql:
                return {
                    "work_id": "issue-44",
                    "source_issue_number": 44,
                    "title": "Task A",
                    "status": "ready",
                    "task_type": "documentation",
                    "attempt_count": 0,
                    "last_failure_reason": None,
                    "next_eligible_at": None,
                }
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_job_detail(
        FakeConnection(), repo="codefromkarl/stardrifter", job_id=9
    )

    assert payload["job"]["id"] == 9
    assert payload["story"]["story_issue_number"] == 21
    assert payload["task"]["work_id"] == "issue-44"


def test_get_job_detail_reads_log_preview(tmp_path):
    log_path = tmp_path / "job.log"
    log_path.write_text("line 1\nline 2\n", encoding="utf-8")

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchone(self):
            if "FROM execution_job" in self.last_sql:
                return {
                    "id": 9,
                    "repo": "codefromkarl/stardrifter",
                    "job_kind": "story_decomposition",
                    "status": "running",
                    "story_issue_number": None,
                    "work_id": None,
                    "launch_backend": "console",
                    "worker_name": "console-story-21",
                    "pid": 4242,
                    "command": "story-command",
                    "log_path": str(log_path),
                    "started_at": "2026-03-25T10:00:00+00:00",
                    "finished_at": None,
                    "exit_code": None,
                }
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_job_detail(
        FakeConnection(), repo="codefromkarl/stardrifter", job_id=9
    )

    assert payload["log_preview"]["available"] is True
    assert "line 1" in payload["log_preview"]["content"]


@pytest.mark.usefixtures("postgres_test_db")
def test_list_epic_rows_integration_returns_real_epic_aggregates(
    postgres_test_db: str,
):
    repo = f"codefromkarl/stardrifter-epics-{uuid4().hex[:8]}"
    epic_issue_number = 8813
    story_issue_number = 8821

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    epic_issue_number,
                    "[Epic][Lane 88] Integration Aggregate Epic",
                    "Lane 88",
                    "approved",
                    "active",
                    "wave-8",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    story_issue_number,
                    epic_issue_number,
                    "[Story][88-A] Integration Aggregate Story",
                    "Lane 88",
                    "medium",
                    "approved",
                    "active",
                    "wave-8",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "issue-8844",
                    repo,
                    "Integration aggregate task A",
                    "Lane 88",
                    "wave-8",
                    "ready",
                    "low",
                    8844,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/agg-a.md"]}',
                    "issue-8845",
                    repo,
                    "Integration aggregate task B",
                    "Lane 88",
                    "wave-8",
                    "in_progress",
                    "low",
                    8845,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/agg-b.md"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                )
                VALUES (%s, %s, %s, %s, %s, NOW() + interval '5 minutes', %s)
                """,
                (
                    "issue-8845",
                    "worker-agg",
                    "/tmp/issue-8845",
                    "task/8845",
                    "lease-8845",
                    '["docs/agg-b.md"]',
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, worker_name, pid, command, log_path, launch_backend
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "story_decomposition",
                    "running",
                    story_issue_number,
                    "console-story-8821",
                    8821,
                    "story-command",
                    "/tmp/story-8821.log",
                    "console",
                ),
            )
            cursor.execute(
                """
                INSERT INTO epic_execution_state (
                    repo, epic_issue_number, status,
                    completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (
                    repo,
                    epic_issue_number,
                    "active",
                    "[]",
                    "[]",
                    "[8821]",
                ),
            )
        connection.commit()

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        payload = list_epic_rows(connection, repo=repo)

    epic = next(
        row for row in payload["rows"] if row["epic_issue_number"] == epic_issue_number
    )
    assert epic["story_count"] == 1
    assert epic["task_count"] == 2
    assert epic["ready_task_count"] == 1
    assert epic["in_progress_task_count"] == 1
    assert epic["active_queue_task_count"] == 2
    assert epic["running_job_count"] == 1
    assert epic["execution_state_status"] == "active"
    assert epic["remaining_story_count"] == 1
    assert epic["queued_for_epic_decomposition"] is False
    assert "story_summaries" not in epic


@pytest.mark.usefixtures("postgres_test_db")
def test_list_epic_story_tree_integration_returns_real_epic_story_task_hierarchy(
    postgres_test_db: str,
):
    repo = f"codefromkarl/stardrifter-tree-{uuid4().hex[:8]}"
    epic_issue_number = 9913
    story_issue_number = 9921
    task_issue_numbers = (9944, 9945)
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    epic_issue_number,
                    "[Epic][Lane 91] Integration Test Epic",
                    "Lane 01",
                    "approved",
                    "active",
                    "wave-1",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    story_issue_number,
                    epic_issue_number,
                    "[Story][91-A] Integration Test Story",
                    "Lane 01",
                    "medium",
                    "approved",
                    "active",
                    "wave-1",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "issue-44",
                    repo,
                    "[91-DOC] Integration Task A",
                    "Lane 01",
                    "wave-1",
                    "done",
                    "low",
                    task_issue_numbers[0],
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/status.md"]}',
                    "issue-45",
                    repo,
                    "[91-DOC] Integration Task B",
                    "Lane 01",
                    "wave-1",
                    "in_progress",
                    "low",
                    task_issue_numbers[1],
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/cleanup.md"]}',
                ),
            )
        connection.commit()

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        payload = list_epic_story_tree(connection, repo=repo)

    epic = next(
        row for row in payload["rows"] if row["epic_issue_number"] == epic_issue_number
    )
    assert len(epic["story_summaries"]) == 1

    story = epic["story_summaries"][0]
    assert story["story_issue_number"] == story_issue_number
    assert story["task_count"] == 2
    assert story["in_progress_task_count"] == 1
    assert len(story["task_summaries"]) == 2
    assert story["task_summaries"][0]["work_id"] == "issue-44"
    assert story["task_summaries"][1]["status"] == "in_progress"


@pytest.mark.usefixtures("postgres_test_db")
def test_get_epic_detail_integration_returns_stories_active_tasks_and_running_jobs(
    postgres_test_db: str,
):
    repo = f"codefromkarl/stardrifter-epic-detail-{uuid4().hex[:8]}"
    epic_issue_number = 7713
    story_issue_number = 7721

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    epic_issue_number,
                    "Epic Detail",
                    "Lane 77",
                    "approved",
                    "active",
                    "wave-7",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    story_issue_number,
                    epic_issue_number,
                    "Story Detail",
                    "Lane 77",
                    "medium",
                    "approved",
                    "active",
                    "wave-7",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "issue-7744",
                    repo,
                    "Epic detail task",
                    "Lane 77",
                    "wave-7",
                    "in_progress",
                    "low",
                    7744,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/epic-detail.md"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                ) VALUES (%s, %s, %s, %s, %s, NOW() + interval '5 minutes', %s)
                """,
                (
                    "issue-7744",
                    "worker-epic",
                    "/tmp/issue-7744",
                    "task/7744",
                    "lease-7744",
                    '["docs/epic-detail.md"]',
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, worker_name, pid, command, log_path, launch_backend
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "story_decomposition",
                    "running",
                    story_issue_number,
                    "console-story-7721",
                    7721,
                    "story-command",
                    "/tmp/story-7721.log",
                    "console",
                ),
            )
            cursor.execute(
                """
                INSERT INTO epic_execution_state (
                    repo, epic_issue_number, status,
                    completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (repo, epic_issue_number, "active", "[]", "[]", "[7721]"),
            )
        connection.commit()

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        payload = get_epic_detail(
            connection, repo=repo, epic_issue_number=epic_issue_number
        )

    assert payload["epic"]["issue_number"] == epic_issue_number
    assert len(payload["stories"]) == 1
    assert payload["stories"][0]["story_issue_number"] == story_issue_number
    assert len(payload["active_tasks"]) == 1
    assert payload["active_tasks"][0]["work_id"] == "issue-7744"
    assert len(payload["running_jobs"]) == 1
    assert payload["running_jobs"][0]["story_issue_number"] == story_issue_number
    assert payload["execution_state"]["status"] == "active"


@pytest.mark.usefixtures("postgres_test_db")
def test_get_story_detail_integration_returns_tasks_jobs_and_queue_context(
    postgres_test_db: str,
):
    repo = f"codefromkarl/stardrifter-story-detail-{uuid4().hex[:8]}"
    epic_issue_number = 6613
    story_issue_number = 6621

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    epic_issue_number,
                    "Epic For Story Detail",
                    "Lane 66",
                    "approved",
                    "active",
                    "wave-6",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    story_issue_number,
                    epic_issue_number,
                    "Story For Detail",
                    "Lane 66",
                    "medium",
                    "approved",
                    "active",
                    "wave-6",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                ) VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "issue-6644",
                    repo,
                    "Story detail task A",
                    "Lane 66",
                    "wave-6",
                    "ready",
                    "low",
                    6644,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/story-a.md"]}',
                    "issue-6645",
                    repo,
                    "Story detail task B",
                    "Lane 66",
                    "wave-6",
                    "done",
                    "low",
                    6645,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/story-b.md"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, worker_name, pid, command, log_path, launch_backend
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "story_decomposition",
                    "running",
                    story_issue_number,
                    "console-story-6621",
                    6621,
                    "story-command",
                    "/tmp/story-6621.log",
                    "console",
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, work_id, worker_name, pid, command, log_path, launch_backend
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "task_execution",
                    "running",
                    story_issue_number,
                    "issue-6644",
                    "worker-6644",
                    6644,
                    "task-command",
                    "/tmp/task-6644.log",
                    "console",
                ),
            )
        connection.commit()

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        payload = get_story_detail(
            connection, repo=repo, story_issue_number=story_issue_number
        )

    assert payload["story"]["story_issue_number"] == story_issue_number
    assert payload["story"]["epic_issue_number"] == epic_issue_number
    assert len(payload["tasks"]) == 2
    assert len(payload["jobs"]) == 2
    assert payload["jobs"][0]["story_issue_number"] == story_issue_number
    assert payload["decomposition_queue"] == {}


def test_get_story_detail_falls_back_when_story_verification_run_table_is_missing():
    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            if "FROM story_verification_run" in sql:
                raise psycopg.errors.UndefinedTable(
                    'relation "story_verification_run" does not exist'
                )

        def fetchone(self):
            if "NULL::text AS verification_status" in self.last_sql:
                return {
                    "story_issue_number": 302,
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 301,
                    "epic_title": "Smoke Epic",
                    "title": "Smoke Story",
                    "lane": "lane-1",
                    "complexity": "medium",
                    "program_status": "approved",
                    "execution_status": "active",
                    "active_wave": "wave-1",
                    "notes": None,
                    "story_pull_number": None,
                    "story_pull_url": None,
                    "last_merge_succeeded": None,
                    "last_promotion_succeeded": None,
                    "merge_commit_sha": None,
                    "promotion_commit_sha": None,
                    "story_integration_blocked_reason": None,
                    "story_integration_summary": None,
                    "story_integration_created_at": None,
                    "verification_status": None,
                    "verification_summary": None,
                    "verification_check_type": None,
                }
            if "GET_STORY_DECOMPOSITION_QUEUE_QUERY" in self.last_sql:
                return None
            return None

        def fetchall(self):
            if "FROM work_item wi" in self.last_sql:
                return [
                    {
                        "work_id": "issue-smoke-task",
                        "source_issue_number": 44,
                        "title": "Smoke Task",
                        "status": "ready",
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "wave": "wave-1",
                        "lane": "lane-1",
                        "blocked_reason": None,
                        "decision_required": False,
                        "attempt_count": 0,
                        "last_failure_reason": None,
                        "next_eligible_at": None,
                        "in_active_queue": False,
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    payload = get_story_detail(
        FakeConnection(), repo="codefromkarl/stardrifter", story_issue_number=302
    )

    assert payload["story"]["story_issue_number"] == 302
    assert payload["story"]["verification_status"] is None
    assert payload["tasks"][0]["work_id"] == "issue-smoke-task"


@pytest.mark.usefixtures("postgres_test_db")
def test_get_task_detail_integration_returns_related_story_epic_runs_and_claim(
    postgres_test_db: str,
):
    repo = f"codefromkarl/stardrifter-task-detail-{uuid4().hex[:8]}"
    epic_issue_number = 5513
    story_issue_number = 5521
    work_id = "issue-5544"

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    epic_issue_number,
                    "Epic For Task Detail",
                    "Lane 55",
                    "approved",
                    "active",
                    "wave-5",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    story_issue_number,
                    epic_issue_number,
                    "Story For Task Detail",
                    "Lane 55",
                    "medium",
                    "approved",
                    "active",
                    "wave-5",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO github_issue_import_batch (repo)
                VALUES (%s)
                RETURNING id
                """,
                (repo,),
            )
            batch_row = cursor.fetchone()
            assert batch_row is not None
            batch_id = cast(Any, batch_row)["id"]
            cursor.execute(
                """
                INSERT INTO github_issue_snapshot (batch_id, repo, issue_number, raw_json)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (batch_id, repo, 5544, "{}"),
            )
            snapshot_row = cursor.fetchone()
            assert snapshot_row is not None
            snapshot_id = cast(Any, snapshot_row)["id"]
            cursor.execute(
                """
                INSERT INTO github_issue_normalized (
                    repo, issue_number, title, url, github_state, import_state, status_label, body, source_snapshot_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    5544,
                    "Task source issue",
                    "https://example.test/issues/5544",
                    "open",
                    "imported",
                    "In Progress",
                    "body",
                    snapshot_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json, attempt_count, last_failure_reason, decision_required
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (
                    work_id,
                    repo,
                    "Task Detail Work Item",
                    "Lane 55",
                    "wave-5",
                    "in_progress",
                    "low",
                    5544,
                    story_issue_number,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/task-detail.md"]}',
                    2,
                    "timeout",
                    False,
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                ) VALUES (%s, %s, %s, %s, %s, NOW() + interval '5 minutes', %s)
                """,
                (
                    work_id,
                    "worker-task",
                    "/tmp/issue-5544",
                    "task/5544",
                    "lease-5544",
                    '["docs/task-detail.md"]',
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_run (
                    work_id, worker_name, status, branch_name, command_digest, summary, exit_code, elapsed_ms, stdout_digest, stderr_digest, result_payload_json, started_at, finished_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
                RETURNING id
                """,
                (
                    work_id,
                    "worker-task",
                    "done",
                    "task/5544",
                    "digest",
                    "run summary",
                    1,
                    1234,
                    "stdout",
                    "stderr",
                    '{"reason_code": "timeout", "outcome": "retryable"}',
                ),
            )
            run_row = cursor.fetchone()
            assert run_row is not None
            run_id = cast(Any, run_row)["id"]
            cursor.execute(
                """
                INSERT INTO verification_evidence (
                    run_id, check_type, command, passed, output_digest, exit_code
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    "pytest",
                    "pytest tests/test_task.py",
                    False,
                    "verify-digest",
                    1,
                ),
            )
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, work_id, worker_name, pid, command, log_path, launch_backend
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "task_execution",
                    "running",
                    story_issue_number,
                    work_id,
                    "worker-task",
                    5544,
                    "task-command",
                    "/tmp/task-5544.log",
                    "console",
                ),
            )
        connection.commit()

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        payload = get_task_detail(connection, repo=repo, work_id=work_id)

    assert payload["task"]["id"] == work_id
    assert payload["task"]["story_issue_number"] == story_issue_number
    assert payload["task"]["epic_issue_number"] == epic_issue_number
    assert payload["task"]["source_issue_title"] == "Task source issue"
    assert payload["active_claim"]["worker_name"] == "worker-task"
    assert len(payload["recent_runs"]) == 1
    assert payload["recent_runs"][0]["verification_passed"] is False
    assert len(payload["jobs"]) == 1
    assert payload["retry_context"]["latest_failure_reason_code"] == "timeout"
