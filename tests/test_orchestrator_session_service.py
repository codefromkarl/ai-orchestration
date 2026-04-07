from __future__ import annotations

from taskplane.models import OperatorRequest
from taskplane.models import WorkItem
from taskplane.orchestrator_session_service import (
    launch_supervisor_for_orchestrator_session,
    handle_orchestrator_session_action,
    start_orchestrator_session,
    watch_orchestrator_session,
)
from taskplane.repository import InMemoryControlPlaneRepository


def _repository() -> InMemoryControlPlaneRepository:
    return InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )


def test_start_orchestrator_session_creates_session_and_tracks_launches() -> None:
    repository = _repository()
    launched: list[dict[str, object]] = []

    def fake_launcher(*, repo: str, dsn: str, session_id: str, story_issue_number=None):
        launched.append(
            {
                "repo": repo,
                "dsn": dsn,
                "session_id": session_id,
                "story_issue_number": story_issue_number,
            }
        )
        return {
            "launched_jobs": [
                {
                    "id": 11,
                    "job_kind": "story_worker",
                    "status": "running",
                    "story_issue_number": 123,
                }
            ],
            "watched_story_issue_numbers": [123],
        }

    result = start_orchestrator_session(
        repository=repository,
        repo="owner/repo",
        dsn="postgresql://example",
        host_tool="claude_code",
        started_by="operator",
        launch_fn=fake_launcher,
    )

    assert result.session.repo == "owner/repo"
    assert result.session.host_tool == "claude_code"
    assert result.launched_jobs[0]["story_issue_number"] == 123
    assert launched[0]["session_id"] == result.session.id
    assert result.session.current_phase == "plan"
    assert (
        result.session.objective_summary
        == "Advance repo owner/repo through orchestrator session"
    )
    assert (
        result.session.plan_summary
        == "Launch work, observe runtime facts, and decide whether to continue, verify, or escalate."
    )
    assert (
        result.session.handoff_summary
        == "Session started; waiting for runtime observations and verification evidence."
    )
    assert result.session.next_action_json["action_kind"] == "launch_session"
    assert result.session.milestones_json[0]["milestone_id"] == "session-bootstrap"
    assert result.session.plan_version == 1
    assert result.session.supersedes_plan_id is None
    assert result.session.replan_events_json == []
    assert result.session.completion_contract_json["approval_required"] is False
    assert result.session.completion_contract_json[
        "required_verification_profiles"
    ] == ["task_verifier"]


def test_watch_orchestrator_session_returns_jobs_and_escalations() -> None:
    repository = _repository()
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
    repository.record_operator_request(
        OperatorRequest(
            repo="owner/repo",
            epic_issue_number=42,
            reason_code="progress_timeout",
            summary="Need operator help",
        )
    )
    from taskplane.models import NaturalLanguageIntent

    repository.record_natural_language_intent(
        NaturalLanguageIntent(
            id="intent-1",
            repo="owner/repo",
            prompt="Clarify auth scope",
            status="awaiting_clarification",
            summary="Need scope confirmation",
        )
    )
    repository.work_items.append(
        WorkItem(
            id="task-1",
            repo="owner/repo",
            title="Needs operator decision",
            lane="general",
            wave="Direct",
            status="blocked",
            blocked_reason="waiting_operator",
            decision_required=True,
        )
    )
    repository.work_items_by_id["task-1"] = repository.work_items[-1]

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["session"].id == session.id
    assert payload["jobs"][0]["id"] == 11
    assert payload["operator_requests"][0].reason_code == "progress_timeout"
    assert payload["intents"][0].id == "intent-1"
    assert payload["blocked_tasks"][0].id == "task-1"
    assert payload["recommended_actions"]


def test_watch_orchestrator_session_returns_phase_and_compact_summary() -> None:
    repository = _repository()
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
    repository.work_items.append(
        WorkItem(
            id="task-1",
            repo="owner/repo",
            title="Needs operator decision",
            lane="general",
            wave="Direct",
            status="blocked",
            blocked_reason="waiting_operator",
            decision_required=True,
        )
    )
    repository.work_items_by_id["task-1"] = repository.work_items[-1]

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["current_phase"] == "escalate"
    assert payload["canonical_loop"] == [
        "observe",
        "plan",
        "act",
        "verify",
        "decide_next",
    ]
    compact_summary = payload["compact_summary"]
    assert (
        compact_summary["objective_summary"]
        == "Advance repo owner/repo through orchestrator session"
    )
    assert (
        compact_summary["plan_summary"]
        == "Review blocked work, pending intents, and running jobs before deciding whether to continue or escalate."
    )
    assert (
        compact_summary["handoff_summary"]
        == "1 blocked task(s), 0 pending intent(s), 1 running job(s)."
    )
    assert (
        compact_summary["what_changed"]
        == "Session is waiting on blocked work triage before the loop can continue."
    )
    assert (
        compact_summary["what_remains"]
        == "Resolve blocked tasks and clear running-job verification state."
    )
    assert compact_summary["operator_requirement"] == "operator input required"
    assert (
        compact_summary["what_passed"]
        == "Session context refresh completed for current blocked and running work."
    )
    assert (
        compact_summary["what_failed"]
        == "Blocked tasks still prevent the loop from continuing automatically."
    )
    assert payload["next_action"]["action_kind"] == "inspect_blockers"
    assert payload["milestones"][0]["milestone_id"] == "blocked-work-review"
    assert payload["plan_version"] == 1
    assert payload["replan_events"] == []
    assert payload["completion_contract"]["approval_required"] is False
    assert payload["decision_state"]["decision"] == "escalate"
    assert payload["decision_state"]["requires_operator"] is True


def test_watch_orchestrator_session_exposes_replan_history() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
        watch_scope_json={"story_issue_numbers": [123]},
        plan_version=3,
        supersedes_plan_id="plan-v2",
        replan_events_json=[
            {
                "trigger_type": "verification_failure",
                "reason_summary": "Verifier failed after the first act phase.",
                "previous_plan_id": "plan-v2",
                "new_plan_id": "plan-v3",
            }
        ],
    )

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["plan_version"] == 3
    assert payload["supersedes_plan_id"] == "plan-v2"
    assert payload["replan_events"][0]["trigger_type"] == "verification_failure"
    assert payload["decision_state"]["decision"] == "replan"
    assert payload["decision_state"]["requires_operator"] is False


def test_watch_orchestrator_session_exposes_completion_contract() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
        watch_scope_json={"story_issue_numbers": [123]},
        completion_contract_json={
            "required_verification_profiles": ["task_verifier", "pytest"],
            "required_evidence_classes": ["verification_evidence"],
            "approval_required": True,
            "expected_artifacts": ["execution_run", "verification_result"],
        },
    )

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["completion_contract"]["approval_required"] is True
    assert payload["completion_contract"]["expected_artifacts"] == [
        "execution_run",
        "verification_result",
    ]


def test_watch_orchestrator_session_decision_state_prefers_verify_for_running_jobs() -> (
    None
):
    repository = _repository()
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

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["decision_state"]["decision"] == "verify"
    assert payload["decision_state"]["requires_operator"] is False
    compact_summary = payload["compact_summary"]
    assert (
        compact_summary["what_changed"]
        == "Session is waiting for running work to be verified before deciding the next transition."
    )
    assert (
        compact_summary["what_remains"]
        == "Review verification results for active jobs."
    )
    assert compact_summary["operator_requirement"] == "operator input not required"
    assert (
        compact_summary["what_passed"]
        == "Runtime work is still active and available for verification review."
    )
    assert (
        compact_summary["what_failed"]
        == "No verification outcome has been recorded yet for the active jobs."
    )


def test_watch_orchestrator_session_decision_state_replans_for_failed_terminal_jobs() -> (
    None
):
    repository = _repository()
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
            "status": "failed",
            "story_issue_number": 123,
        },
    )

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["current_phase"] == "decide_next"
    assert payload["decision_state"]["decision"] == "replan"
    assert payload["decision_state"]["requires_operator"] is False


def test_watch_orchestrator_session_decision_state_continues_for_successful_terminal_jobs() -> (
    None
):
    repository = _repository()
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
            "status": "completed",
            "story_issue_number": 123,
        },
    )

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert payload["current_phase"] == "decide_next"
    assert payload["decision_state"]["decision"] == "continue"
    assert payload["decision_state"]["requires_operator"] is False


def test_watch_orchestrator_session_filters_blocked_tasks_by_watched_story_scope() -> (
    None
):
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
        watch_scope_json={"story_issue_numbers": [123]},
    )
    scoped_task = WorkItem(
        id="task-scope",
        repo="owner/repo",
        title="Scoped blocked task",
        lane="general",
        wave="Direct",
        status="blocked",
        canonical_story_issue_number=123,
        story_issue_numbers=(123,),
        blocked_reason="waiting_operator",
        decision_required=True,
    )
    other_task = WorkItem(
        id="task-other",
        repo="owner/repo",
        title="Other blocked task",
        lane="general",
        wave="Direct",
        status="blocked",
        canonical_story_issue_number=999,
        story_issue_numbers=(999,),
        blocked_reason="waiting_operator",
        decision_required=True,
    )
    repository.work_items.extend([scoped_task, other_task])
    repository.work_items_by_id[scoped_task.id] = scoped_task
    repository.work_items_by_id[other_task.id] = other_task

    payload = watch_orchestrator_session(repository=repository, session_id=session.id)

    assert [task.id for task in payload["blocked_tasks"]] == ["task-scope"]


def test_handle_orchestrator_session_action_can_ack_operator_request() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
    )
    repository.record_operator_request(
        OperatorRequest(
            repo="owner/repo",
            epic_issue_number=42,
            reason_code="progress_timeout",
            summary="Need operator help",
        )
    )

    result = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="ack_operator_request",
        payload={
            "repo": "owner/repo",
            "epic_issue_number": 42,
            "reason_code": "progress_timeout",
            "closed_reason": "approved",
        },
    )

    assert result["action"] == "ack_operator_request"
    assert result["closed_request"].closed_reason == "approved"


def test_handle_orchestrator_session_action_can_answer_intent() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
    )

    class FakeIntakeService:
        def answer_intent(self, *, intent_id: str, answer: str):
            return type("Intent", (), {"id": intent_id, "status": "awaiting_review"})()

    result = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="answer_intent",
        payload={"intent_id": "intent-1", "answer": "Use JWT"},
        intake_service=FakeIntakeService(),
    )

    assert result["action"] == "answer_intent"
    assert result["intent"].id == "intent-1"


def test_handle_orchestrator_session_action_can_approve_intent() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
    )

    class FakeIntakeService:
        def approve_intent(self, *, intent_id: str, approver: str):
            return type("Intent", (), {"id": intent_id, "status": "promoted"})()

    result = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="approve_intent",
        payload={"intent_id": "intent-1", "approver": "operator"},
        intake_service=FakeIntakeService(),
    )

    assert result["action"] == "approve_intent"
    assert result["intent"].status == "promoted"


def test_handle_orchestrator_session_action_can_reject_and_revise_intent() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
    )

    class FakeIntakeService:
        def reject_intent(self, *, intent_id: str, reviewer: str, reason: str):
            return type(
                "Intent",
                (),
                {"id": intent_id, "status": "rejected", "review_feedback": reason},
            )()

        def revise_intent(self, *, intent_id: str, reviewer: str, feedback: str):
            return type(
                "Intent",
                (),
                {
                    "id": intent_id,
                    "status": "awaiting_clarification",
                    "review_feedback": feedback,
                },
            )()

    rejected = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="reject_intent",
        payload={
            "intent_id": "intent-1",
            "reason": "Too broad",
            "reviewer": "operator",
        },
        intake_service=FakeIntakeService(),
    )
    revised = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="revise_intent",
        payload={
            "intent_id": "intent-1",
            "feedback": "Clarify MVP",
            "reviewer": "operator",
        },
        intake_service=FakeIntakeService(),
    )

    assert rejected["intent"].status == "rejected"
    assert revised["intent"].status == "awaiting_clarification"


def test_handle_orchestrator_session_action_can_record_replan() -> None:
    repository = _repository()
    session = repository.create_orchestrator_session(
        repo="owner/repo",
        host_tool="claude_code",
        started_by="operator",
        plan_version=1,
        next_action_json={"action_kind": "observe_runtime"},
        milestones_json=[{"milestone_id": "m1", "status": "active"}],
    )

    result = handle_orchestrator_session_action(
        repository=repository,
        session_id=session.id,
        action_type="record_replan",
        payload={
            "current_phase": "plan",
            "plan_summary": "Revise plan after verifier feedback.",
            "handoff_summary": "Verifier failed; replan required.",
            "next_action_json": {"action_kind": "replan"},
            "milestones_json": [{"milestone_id": "m2", "status": "active"}],
            "plan_version": 2,
            "supersedes_plan_id": "plan-v1",
            "replan_event": {
                "trigger_type": "verification_failure",
                "previous_plan_id": "plan-v1",
                "new_plan_id": "plan-v2",
            },
            "completion_contract_json": {"approval_required": False},
        },
    )

    assert result["action"] == "record_replan"
    updated = result["session"]
    assert updated.plan_version == 2
    assert updated.supersedes_plan_id == "plan-v1"
    assert updated.next_action_json["action_kind"] == "replan"
    assert updated.milestones_json[0]["milestone_id"] == "m2"
    assert updated.replan_events_json[0]["new_plan_id"] == "plan-v2"


def test_launch_supervisor_for_orchestrator_session_passes_session_id(tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return 2

    payload = launch_supervisor_for_orchestrator_session(
        repo="owner/repo",
        dsn="postgresql://example",
        session_id="orch-123",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        supervisor_runner=fake_runner,
        connection=object(),
    )

    assert captured["orchestrator_session_id"] == "orch-123"
    assert payload["launched_jobs"][0]["id"] == 1
