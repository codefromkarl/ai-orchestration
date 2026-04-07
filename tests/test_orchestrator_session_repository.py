from __future__ import annotations

from typing import Any, cast

import pytest

psycopg = pytest.importorskip("psycopg")
dict_row = pytest.importorskip("psycopg.rows").dict_row

from taskplane.repository import PostgresControlPlaneRepository


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_repository_persists_orchestrator_session_and_jobs(
    postgres_test_db: str,
):
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        repository = PostgresControlPlaneRepository(connection)

        session = repository.create_orchestrator_session(
            repo="owner/repo",
            host_tool="claude_code",
            started_by="operator",
            watch_scope_json={"story_issue_numbers": [123]},
        )
        repository.record_orchestrator_session_job(
            session_id=session.id,
            job={
                "id": 11,
                "job_kind": "story_worker",
                "status": "running",
                "story_issue_number": 123,
            },
        )

        loaded = repository.get_orchestrator_session(session.id)
        jobs = repository.list_orchestrator_session_jobs(session.id)

    assert loaded is not None
    assert loaded.repo == "owner/repo"
    assert loaded.host_tool == "claude_code"
    assert jobs[0]["id"] == 11
    assert jobs[0]["job_kind"] == "story_worker"


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_repository_persists_orchestrator_session_planning_summaries(
    postgres_test_db: str,
):
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        repository = PostgresControlPlaneRepository(connection)

        session = repository.create_orchestrator_session(
            repo="owner/repo",
            host_tool="claude_code",
            started_by="operator",
            watch_scope_json={"story_issue_numbers": [123]},
            current_phase="plan",
            objective_summary="Advance repo owner/repo through orchestrator session",
            plan_summary="Break the current story into verified milestones before execution.",
            handoff_summary="No handoff yet.",
        )

        loaded = repository.get_orchestrator_session(session.id)

    assert loaded is not None
    assert loaded.current_phase == "plan"
    assert (
        loaded.objective_summary
        == "Advance repo owner/repo through orchestrator session"
    )
    assert (
        loaded.plan_summary
        == "Break the current story into verified milestones before execution."
    )
    assert loaded.handoff_summary == "No handoff yet."


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_repository_persists_orchestrator_session_structured_planning_artifacts(
    postgres_test_db: str,
):
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        repository = PostgresControlPlaneRepository(connection)

        session = repository.create_orchestrator_session(
            repo="owner/repo",
            host_tool="claude_code",
            started_by="operator",
            watch_scope_json={"story_issue_numbers": [123]},
            next_action_json={
                "action_kind": "decompose_story",
                "target_scope": "story:123",
                "rationale": "Need executable tasks before act phase.",
                "expected_output": "Structured task list",
                "verifier_hint": "validate task specs",
            },
            milestones_json=[
                {
                    "milestone_id": "m1",
                    "summary": "Draft task plan",
                    "status": "active",
                    "completion_criteria": ["task specs recorded"],
                    "ordering": 1,
                }
            ],
        )

        loaded = repository.get_orchestrator_session(session.id)

    assert loaded is not None
    assert loaded.next_action_json["action_kind"] == "decompose_story"
    assert loaded.next_action_json["target_scope"] == "story:123"
    assert loaded.milestones_json[0]["milestone_id"] == "m1"
    assert loaded.milestones_json[0]["status"] == "active"


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_repository_persists_orchestrator_session_plan_versions_and_replan_events(
    postgres_test_db: str,
):
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        repository = PostgresControlPlaneRepository(connection)

        session = repository.create_orchestrator_session(
            repo="owner/repo",
            host_tool="claude_code",
            started_by="operator",
            watch_scope_json={"story_issue_numbers": [123]},
            plan_version=2,
            supersedes_plan_id="plan-v1",
            replan_events_json=[
                {
                    "trigger_type": "verification_failure",
                    "reason_summary": "Initial plan failed verifier checks.",
                    "previous_plan_id": "plan-v1",
                    "new_plan_id": "plan-v2",
                }
            ],
        )

        loaded = repository.get_orchestrator_session(session.id)

    assert loaded is not None
    assert loaded.plan_version == 2
    assert loaded.supersedes_plan_id == "plan-v1"
    assert loaded.replan_events_json[0]["trigger_type"] == "verification_failure"
    assert loaded.replan_events_json[0]["new_plan_id"] == "plan-v2"
