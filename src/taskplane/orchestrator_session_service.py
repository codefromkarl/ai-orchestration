from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .scheduling_loop import run_supervisor_iteration


_CANONICAL_LOOP = ["observe", "plan", "act", "verify", "decide_next"]


@dataclass(frozen=True)
class OrchestratorStartResult:
    session: Any
    launched_jobs: list[dict[str, Any]]
    watched_story_issue_numbers: list[int]


def start_orchestrator_session(
    *,
    repository: Any,
    repo: str,
    dsn: str,
    host_tool: str,
    started_by: str,
    story_issue_number: int | None = None,
    launch_fn: Any,
) -> OrchestratorStartResult:
    session = repository.create_orchestrator_session(
        repo=repo,
        host_tool=host_tool,
        started_by=started_by,
        watch_scope_json={},
        current_phase="plan",
        objective_summary=f"Advance repo {repo} through orchestrator session",
        plan_summary="Launch work, observe runtime facts, and decide whether to continue, verify, or escalate.",
        handoff_summary="Session started; waiting for runtime observations and verification evidence.",
        next_action_json={
            "action_kind": "launch_session",
            "target_scope": f"repo:{repo}",
            "rationale": "Bootstrap session state and start orchestrated work.",
            "expected_output": "running jobs and watched stories",
            "verifier_hint": "confirm session jobs are recorded",
        },
        milestones_json=[
            {
                "milestone_id": "session-bootstrap",
                "summary": "Bootstrap orchestrator session and launch initial work.",
                "status": "active",
                "completion_criteria": ["session created", "launch jobs recorded"],
                "ordering": 1,
            }
        ],
        plan_version=1,
        supersedes_plan_id=None,
        replan_events_json=[],
        completion_contract_json={
            "required_verification_profiles": ["task_verifier"],
            "required_evidence_classes": ["verification_evidence"],
            "approval_required": False,
            "expected_artifacts": ["execution_run", "verification_result"],
        },
    )
    launch_payload = launch_fn(
        repo=repo,
        dsn=dsn,
        session_id=session.id,
        story_issue_number=story_issue_number,
    )
    launched_jobs = list(launch_payload.get("launched_jobs") or [])
    watched_story_issue_numbers = [
        int(value)
        for value in (launch_payload.get("watched_story_issue_numbers") or [])
        if value is not None
    ]
    for job in launched_jobs:
        repository.record_orchestrator_session_job(session_id=session.id, job=job)
    session = repository.update_orchestrator_session_scope(
        session_id=session.id,
        watch_scope_json={"story_issue_numbers": watched_story_issue_numbers},
    )
    return OrchestratorStartResult(
        session=session,
        launched_jobs=launched_jobs,
        watched_story_issue_numbers=watched_story_issue_numbers,
    )


def watch_orchestrator_session(*, repository: Any, session_id: str) -> dict[str, Any]:
    session = repository.get_orchestrator_session(session_id)
    if session is None:
        raise KeyError(session_id)
    watch_scope = dict(session.watch_scope_json or {})
    scoped_story_issue_numbers = {
        int(value)
        for value in (watch_scope.get("story_issue_numbers") or [])
        if value is not None
    }
    intents = repository.list_natural_language_intents(repo=session.repo)
    blocked_tasks_all = [
        item
        for item in repository.list_work_items()
        if item.repo == session.repo and item.status == "blocked"
    ]
    if scoped_story_issue_numbers:
        scoped_blocked_tasks = [
            item
            for item in blocked_tasks_all
            if (item.canonical_story_issue_number in scoped_story_issue_numbers)
            or any(
                story in scoped_story_issue_numbers
                for story in item.story_issue_numbers
            )
        ]
        blocked_tasks = scoped_blocked_tasks or blocked_tasks_all
    else:
        blocked_tasks = blocked_tasks_all
    recommended_actions: list[str] = []
    for intent in intents:
        if intent.status == "awaiting_clarification":
            recommended_actions.append(
                f'/tp-handle --session {session.id} --intent {intent.id} --answer "..."'
            )
        elif intent.status == "awaiting_review":
            recommended_actions.append(
                f"/tp-handle --session {session.id} --intent {intent.id} --approve"
            )
    for item in blocked_tasks:
        if item.decision_required:
            recommended_actions.append(
                f"inspect blocked task {item.id}: {item.blocked_reason or 'decision required'}"
            )
    current_phase = _derive_session_phase(
        blocked_tasks=blocked_tasks,
        intents=intents,
        jobs=repository.list_orchestrator_session_jobs(session_id),
    )
    compact_summary = _build_compact_summary(
        repo=session.repo,
        blocked_tasks=blocked_tasks,
        intents=intents,
        jobs=repository.list_orchestrator_session_jobs(session_id),
        current_phase=current_phase,
    )
    return {
        "session": session,
        "jobs": repository.list_orchestrator_session_jobs(session_id),
        "current_phase": current_phase,
        "canonical_loop": list(_CANONICAL_LOOP),
        "compact_summary": compact_summary,
        "next_action": _build_next_action(
            repo=session.repo,
            current_phase=current_phase,
            blocked_tasks=blocked_tasks,
            intents=intents,
            jobs=repository.list_orchestrator_session_jobs(session_id),
            persisted_next_action=dict(getattr(session, "next_action_json", {}) or {}),
        ),
        "milestones": _build_milestones(
            current_phase=current_phase,
            blocked_tasks=blocked_tasks,
            intents=intents,
            jobs=repository.list_orchestrator_session_jobs(session_id),
            persisted_milestones=list(getattr(session, "milestones_json", []) or []),
        ),
        "plan_version": int(getattr(session, "plan_version", 1) or 1),
        "supersedes_plan_id": getattr(session, "supersedes_plan_id", None),
        "replan_events": list(getattr(session, "replan_events_json", []) or []),
        "completion_contract": _build_completion_contract(
            persisted_completion_contract=dict(
                getattr(session, "completion_contract_json", {}) or {}
            )
        ),
        "decision_state": _build_decision_state(
            current_phase=current_phase,
            blocked_tasks=blocked_tasks,
            intents=intents,
            jobs=repository.list_orchestrator_session_jobs(session_id),
            replan_events=list(getattr(session, "replan_events_json", []) or []),
        ),
        "operator_requests": repository.list_operator_requests(repo=session.repo),
        "intents": intents,
        "blocked_tasks": blocked_tasks,
        "recommended_actions": recommended_actions,
    }


def _derive_session_phase(
    *, blocked_tasks: list[Any], intents: list[Any], jobs: list[dict[str, Any]]
) -> str:
    if any(getattr(task, "decision_required", False) for task in blocked_tasks):
        return "escalate"
    if intents:
        return "plan"
    if jobs:
        return "verify"
    return "observe"


def _build_compact_summary(
    *,
    repo: str,
    blocked_tasks: list[Any],
    intents: list[Any],
    jobs: list[dict[str, Any]],
    current_phase: str,
) -> dict[str, str]:
    plan_summary_by_phase = {
        "observe": "Review current runtime facts before selecting the next planning step.",
        "plan": "Review blocked work, pending intents, and running jobs before deciding whether to continue or escalate.",
        "act": "Execute the current action plan against the selected story or task scope.",
        "verify": "Validate current story execution and pending operator work before deciding the next action.",
        "escalate": "Review blocked work, pending intents, and running jobs before deciding whether to continue or escalate.",
    }
    return {
        "objective_summary": f"Advance repo {repo} through orchestrator session",
        "plan_summary": plan_summary_by_phase.get(
            current_phase,
            "Review blocked work, pending intents, and running jobs before deciding whether to continue or escalate.",
        ),
        "handoff_summary": (
            f"{len(blocked_tasks)} blocked task(s), {len(intents)} pending intent(s), {len(jobs)} running job(s)."
        ),
    }


def _build_next_action(
    *,
    repo: str,
    current_phase: str,
    blocked_tasks: list[Any],
    intents: list[Any],
    jobs: list[dict[str, Any]],
    persisted_next_action: dict[str, Any],
) -> dict[str, Any]:
    if persisted_next_action:
        if current_phase == "escalate":
            return {
                "action_kind": "inspect_blockers",
                "target_scope": f"repo:{repo}",
                "rationale": "Blocked tasks require operator-aware triage before the loop can continue.",
                "expected_output": "operator decision or unblock plan",
                "verifier_hint": "confirm blocker handling path",
            }
        return dict(persisted_next_action)
    if current_phase == "escalate":
        return {
            "action_kind": "inspect_blockers",
            "target_scope": f"repo:{repo}",
            "rationale": "Blocked tasks require operator-aware triage before the loop can continue.",
            "expected_output": "operator decision or unblock plan",
            "verifier_hint": "confirm blocker handling path",
        }
    if intents:
        return {
            "action_kind": "resolve_intents",
            "target_scope": f"repo:{repo}",
            "rationale": "Pending clarification or review blocks the next planning step.",
            "expected_output": "answered or approved intents",
            "verifier_hint": "confirm intent status transitions",
        }
    if jobs:
        return {
            "action_kind": "verify_progress",
            "target_scope": f"repo:{repo}",
            "rationale": "Running jobs require verification-oriented observation before scheduling more work.",
            "expected_output": "updated session verification context",
            "verifier_hint": "confirm execution progress is reflected",
        }
    return {
        "action_kind": "observe_runtime",
        "target_scope": f"repo:{repo}",
        "rationale": "No active blockers or jobs; begin with fresh observation.",
        "expected_output": "observation snapshot",
        "verifier_hint": "confirm session context refreshed",
    }


def _build_milestones(
    *,
    current_phase: str,
    blocked_tasks: list[Any],
    intents: list[Any],
    jobs: list[dict[str, Any]],
    persisted_milestones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if current_phase == "escalate":
        return [
            {
                "milestone_id": "blocked-work-review",
                "summary": "Resolve blocked tasks before resuming the main loop.",
                "status": "active",
                "completion_criteria": [
                    f"blocked tasks reviewed: {len(blocked_tasks)}",
                    "operator path selected",
                ],
                "ordering": 1,
            }
        ]
    if persisted_milestones:
        return [dict(item) for item in persisted_milestones]
    return [
        {
            "milestone_id": "session-observation",
            "summary": "Refresh session context before selecting the next action.",
            "status": "active" if not intents and not jobs else "in_progress",
            "completion_criteria": [
                f"pending intents accounted for: {len(intents)}",
                f"running jobs accounted for: {len(jobs)}",
            ],
            "ordering": 1,
        }
    ]


def _build_completion_contract(
    *, persisted_completion_contract: dict[str, Any]
) -> dict[str, Any]:
    if persisted_completion_contract:
        return dict(persisted_completion_contract)
    return {
        "required_verification_profiles": ["task_verifier"],
        "required_evidence_classes": ["verification_evidence"],
        "approval_required": False,
        "expected_artifacts": ["execution_run", "verification_result"],
    }


def _build_decision_state(
    *,
    current_phase: str,
    blocked_tasks: list[Any],
    intents: list[Any],
    jobs: list[dict[str, Any]],
    replan_events: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(getattr(task, "decision_required", False) for task in blocked_tasks):
        return {
            "decision": "escalate",
            "reason": "blocked work requires operator-visible decision handling",
            "requires_operator": True,
            "current_phase": current_phase,
        }
    if intents:
        return {
            "decision": "plan",
            "reason": "pending intents must be resolved before continuing",
            "requires_operator": False,
            "current_phase": current_phase,
        }
    if jobs:
        return {
            "decision": "verify",
            "reason": "running jobs need verification before the next transition",
            "requires_operator": False,
            "current_phase": current_phase,
        }
    if replan_events:
        return {
            "decision": "replan",
            "reason": "prior replans indicate the next transition should refresh the plan",
            "requires_operator": False,
            "current_phase": current_phase,
        }
    return {
        "decision": "continue",
        "reason": "no blockers or active jobs prevent the loop from continuing",
        "requires_operator": False,
        "current_phase": current_phase,
    }


def handle_orchestrator_session_action(
    *,
    repository: Any,
    session_id: str,
    action_type: str,
    payload: dict[str, Any],
    intake_service: Any | None = None,
) -> dict[str, Any]:
    session = repository.get_orchestrator_session(session_id)
    if session is None:
        raise KeyError(session_id)
    if action_type == "ack_operator_request":
        closed_request = repository.close_operator_request(
            repo=str(payload["repo"]),
            epic_issue_number=int(payload["epic_issue_number"]),
            reason_code=str(payload["reason_code"]),
            closed_reason=str(payload.get("closed_reason") or "approved"),
        )
        return {
            "action": action_type,
            "session": session,
            "closed_request": closed_request,
        }
    if action_type == "answer_intent":
        if intake_service is None:
            raise ValueError("intake_service is required for answer_intent")
        intent = intake_service.answer_intent(
            intent_id=str(payload["intent_id"]),
            answer=str(payload["answer"]),
        )
        return {"action": action_type, "session": session, "intent": intent}
    if action_type == "approve_intent":
        if intake_service is None:
            raise ValueError("intake_service is required for approve_intent")
        intent = intake_service.approve_intent(
            intent_id=str(payload["intent_id"]),
            approver=str(payload.get("approver") or session.started_by),
        )
        return {"action": action_type, "session": session, "intent": intent}
    if action_type == "reject_intent":
        if intake_service is None:
            raise ValueError("intake_service is required for reject_intent")
        intent = intake_service.reject_intent(
            intent_id=str(payload["intent_id"]),
            reviewer=str(payload.get("reviewer") or session.started_by),
            reason=str(payload["reason"]),
        )
        return {"action": action_type, "session": session, "intent": intent}
    if action_type == "revise_intent":
        if intake_service is None:
            raise ValueError("intake_service is required for revise_intent")
        intent = intake_service.revise_intent(
            intent_id=str(payload["intent_id"]),
            reviewer=str(payload.get("reviewer") or session.started_by),
            feedback=str(payload["feedback"]),
        )
        return {"action": action_type, "session": session, "intent": intent}
    raise ValueError(f"unsupported action_type: {action_type}")


def launch_supervisor_for_orchestrator_session(
    *,
    repo: str,
    dsn: str,
    session_id: str,
    project_dir: Path,
    log_dir: Path,
    worktree_root: Path | None,
    connection: Any,
    supervisor_runner: Any = run_supervisor_iteration,
) -> dict[str, Any]:
    launched = supervisor_runner(
        connection=connection,
        repo=repo,
        dsn=dsn,
        project_dir=project_dir,
        log_dir=log_dir,
        worktree_root=worktree_root,
        max_parallel_jobs=2,
        orchestrator_session_id=session_id,
    )
    synthetic_jobs = [
        {
            "id": index + 1,
            "repo": repo,
            "job_kind": "supervisor_spawned",
            "status": "running",
        }
        for index in range(int(launched))
    ]
    return {
        "launched_jobs": synthetic_jobs,
        "watched_story_issue_numbers": [],
    }
