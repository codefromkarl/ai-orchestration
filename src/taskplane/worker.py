from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any
from typing import Callable
from typing import cast
import sys

from ._worker_failure_policy import (
    _classify_execution_failure,
    REQUEUEABLE_EXECUTION_FAILURE_REASONS,
)
from ._worker_execution_context import (
    _build_execution_context,
    _run_verifier_with_context,
)
from ._worker_execution_runtime import (
    _renew_claim_after_prepare,
    _run_executor_with_heartbeat,
)
from .ai_decision_agent import AIDecisionAgent, DecisionOutcome
from ._worker_queue_preparation import (
    PreflightEarlyExit,
    _exclude_previously_completed_in_memory_candidates,
    _materialize_blocked_items,
    _prepare_worker_queue,
    _run_preflight_checks,
)
from .dead_letter_queue import DeadLetterQueue
from .execution_protocol import classify_execution_payload
from .git_committer import CommitResult
from .models import (
    ApprovalEvent,
    ExecutionContext,
    ExecutionGuardrailContext,
    ExecutionRun,
    ExecutionSession,
    SESSION_WAITING_STATUSES,
    VerificationEvidence,
    WorkClaim,
    WorkItem,
    WorkStatus,
)
from .policy_engine import evaluate_policy
from .protocols import (
    ExecutorAdapter,
    invoke_task_writeback,
    SessionManagerProtocol,
    TaskWritebackAdapter,
    VerifierAdapter,
    WorkspaceAdapter,
)
from .repository import WorkerRepository
from .resume_context_builder import build_store_backed_resume_context_builder
from .session_runtime_loop import (
    ExecutorResult as SessionExecutorResult,
    SessionTurnRequest,
    run_session_to_completion,
)
from .session_protocol import (
    SessionRuntimeAdapter,
    coerce_session_runtime_adapter,
)
from .workspace import build_workspace_spec

ALREADY_SATISFIED_OUTCOME = "already_satisfied"

REQUEUEABLE_BACKOFF = timedelta(minutes=5)
DEFAULT_SESSION_MAX_ITERATIONS = 8


def _log_event(
    *,
    dsn: str,
    event_type: str,
    work_id: str | None = None,
    run_id: int | None = None,
    actor: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        import psycopg
        from psycopg.rows import dict_row as _dict_row

        with psycopg.connect(dsn, row_factory=cast(Any, _dict_row)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO event_log (event_type, work_id, run_id, actor, detail)
                    VALUES (%s, %s, %s, %s, %s)""",
                    (event_type, work_id, run_id, actor, detail or {}),
                )
    except Exception:
        pass


def _auto_store_artifacts(
    *,
    dsn: str,
    work_id: str,
    execution_result: "ExecutionResult",
) -> None:
    try:
        from .artifact_store import ArtifactStore

        store = ArtifactStore(dsn=dsn)
        if execution_result.stdout_digest:
            store.record_reference(
                work_id=work_id,
                artifact_type="stdout",
                storage_path=execution_result.stdout_digest,
                content_digest=execution_result.stdout_digest,
                metadata={"worker": "auto"},
                sequence=1,
            )
        if execution_result.stderr_digest:
            store.record_reference(
                work_id=work_id,
                artifact_type="stderr",
                storage_path=execution_result.stderr_digest,
                content_digest=execution_result.stderr_digest,
                metadata={"worker": "auto"},
                sequence=1,
            )
    except Exception:
        pass


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    summary: str
    command_digest: str | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""
    blocked_reason: str | None = None
    decision_required: bool = False
    result_payload_json: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkerCycleResult:
    claimed_work_id: str | None


WorkerSessionRuntime = SessionRuntimeAdapter


def run_worker_cycle(
    *,
    repository: WorkerRepository,
    context: ExecutionGuardrailContext,
    worker_name: str,
    executor: ExecutorAdapter,
    verifier: VerifierAdapter,
    committer: Callable[[WorkItem, ExecutionResult, Path | None], CommitResult]
    | None = None,
    github_writeback: TaskWritebackAdapter | None = None,
    work_item_ids: list[str] | None = None,
    workspace_manager: WorkspaceAdapter | None = None,
    session_runtime: WorkerSessionRuntime | SessionManagerProtocol | bool | None = None,
    dsn: str | None = None,
) -> WorkerCycleResult:
    queue_preparation = _prepare_worker_queue(
        repository=repository,
        work_item_ids=work_item_ids,
        context=context,
        worker_name=worker_name,
    )
    if queue_preparation.early_exit_result is not None:
        if isinstance(queue_preparation.early_exit_result, PreflightEarlyExit):
            return WorkerCycleResult(
                claimed_work_id=queue_preparation.early_exit_result.claimed_work_id
            )
        return queue_preparation.early_exit_result
    evaluation = queue_preparation.evaluation
    work_items = queue_preparation.work_items

    if not evaluation.executable_ids:
        return WorkerCycleResult(claimed_work_id=None)

    claim_workspace_path_by_work_id: dict[str, str] = {}
    claim_branch_name_by_work_id: dict[str, str] = {}
    if workspace_manager is not None:
        work_items_by_id = {item.id: item for item in work_items}
        _best_effort_prewarm_story_workspaces(
            workspace_manager=workspace_manager,
            work_items_by_id=work_items_by_id,
            executable_ids=evaluation.executable_ids,
            worker_name=worker_name,
        )
        for work_id in evaluation.executable_ids:
            candidate = work_items_by_id.get(work_id)
            if candidate is None:
                continue
            workspace_spec = build_workspace_spec(
                work_item=candidate,
                repo_root=workspace_manager.repo_root,
                worktree_root=workspace_manager.worktree_root,
            )
            claim_workspace_path_by_work_id[work_id] = str(
                workspace_spec.workspace_path
            )
            claim_branch_name_by_work_id[work_id] = workspace_spec.branch_name
    print(f"TRACE worker stage=before_claim worker={worker_name}", file=sys.stderr)
    work_item = repository.claim_next_executable_work_item(
        worker_name=worker_name,
        queue_evaluation=evaluation,
        candidate_work_items=work_items,
        workspace_path_by_work_id=claim_workspace_path_by_work_id,
        branch_name_by_work_id=claim_branch_name_by_work_id,
    )
    print(
        f"TRACE worker stage=after_claim worker={worker_name} claimed_work_id={None if work_item is None else work_item.id}",
        file=sys.stderr,
    )
    if work_item is None:
        return WorkerCycleResult(claimed_work_id=None)
    claimed_work_id = work_item.id

    if dsn:
        _log_event(
            dsn=dsn,
            event_type="task_claimed",
            work_id=claimed_work_id,
            actor=worker_name,
            detail={"task_type": work_item.task_type, "lane": work_item.lane},
        )

    workspace_path: Path | None = None
    if workspace_manager is not None:
        try:
            print(
                f"TRACE worker stage=before_prepare worker={worker_name} work_id={claimed_work_id}",
                file=sys.stderr,
            )
            workspace_path = workspace_manager.prepare(
                work_item=work_item,
                worker_name=worker_name,
                repository=repository,
            )
            print(
                f"TRACE worker stage=after_prepare worker={worker_name} work_id={claimed_work_id} workspace={workspace_path}",
                file=sys.stderr,
            )
            _renew_claim_after_prepare(repository, claimed_work_id)
        except Exception:
            repository.delete_work_claim(claimed_work_id)
            repository.update_work_status(
                claimed_work_id,
                "ready",
                blocked_reason=None,
                decision_required=False,
            )
            raise

    try:
        execution_context = _build_execution_context(
            repository=repository,
            work_id=claimed_work_id,
            workspace_path=workspace_path,
        )
        print(
            f"TRACE worker stage=before_executor worker={worker_name} work_id={claimed_work_id}",
            file=sys.stderr,
        )
        execution_result = _run_executor_with_optional_session_runtime(
            executor=executor,
            repository=repository,
            work_id=claimed_work_id,
            work_item=work_item,
            workspace_path=workspace_path,
            execution_context=execution_context,
            session_runtime=session_runtime,
            dsn=dsn,
        )
        if dsn:
            _auto_store_artifacts(
                dsn=dsn,
                work_id=claimed_work_id,
                execution_result=execution_result,
            )
        print(
            f"TRACE worker stage=after_executor worker={worker_name} work_id={claimed_work_id} success={execution_result.success}",
            file=sys.stderr,
        )
        if not execution_result.success:
            failure_finalization = _build_failure_finalization(
                claimed_work_id=claimed_work_id,
                worker_name=worker_name,
                execution_result=execution_result,
                current_attempt_count=work_item.attempt_count,
                branch_name=claim_branch_name_by_work_id.get(claimed_work_id),
            )
            repository.finalize_work_attempt(
                work_id=claimed_work_id,
                status=failure_finalization["status"],
                blocked_reason=failure_finalization["blocked_reason"],
                decision_required=failure_finalization["decision_required"],
                execution_run=failure_finalization["execution_run"],
                attempt_count=failure_finalization["attempt_count"],
                last_failure_reason=failure_finalization["last_failure_reason"],
                next_eligible_at=failure_finalization["next_eligible_at"],
            )
            last_failure_reason = failure_finalization["last_failure_reason"]
            new_attempt_count = failure_finalization["attempt_count"]
            if dsn and last_failure_reason in REQUEUEABLE_EXECUTION_FAILURE_REASONS:
                max_retries = int(os.environ.get("TASKPLANE_MAX_RETRIES", "5"))
                if new_attempt_count >= max_retries:
                    dlq = DeadLetterQueue(dsn)
                    dlq.move_to_dlq(
                        work_id=claimed_work_id,
                        original_status=failure_finalization["status"],
                        failure_reason=last_failure_reason or "unknown",
                        attempt_count=new_attempt_count,
                        last_run_id=None,
                        moved_by=worker_name,
                    )
                    if dsn:
                        _log_event(
                            dsn=dsn,
                            event_type="dlq_moved",
                            work_id=claimed_work_id,
                            actor=worker_name,
                            detail={
                                "failure_reason": last_failure_reason,
                                "attempt_count": new_attempt_count,
                            },
                        )
            if dsn:
                _log_event(
                    dsn=dsn,
                    event_type="task_failed",
                    work_id=claimed_work_id,
                    actor=worker_name,
                    detail={
                        "reason": last_failure_reason,
                        "status": failure_finalization["status"],
                    },
                )
            _write_back_task_issue_status(
                repository=repository,
                work_id=claimed_work_id,
                status=failure_finalization["status"],
                decision_required=failure_finalization["decision_required"],
                github_writeback=github_writeback,
            )
            return WorkerCycleResult(claimed_work_id=claimed_work_id)

        outcome = _extract_outcome(execution_result)
        already_satisfied = outcome == ALREADY_SATISFIED_OUTCOME
        repository.update_work_status(claimed_work_id, "verifying")
        print(
            f"TRACE worker stage=before_verifier worker={worker_name} work_id={claimed_work_id}",
            file=sys.stderr,
        )
        verification = _run_verifier_for_execution_result(
            verifier=verifier,
            work_item=repository.get_work_item(claimed_work_id),
            workspace_path=workspace_path,
            execution_context=execution_context,
            execution_result=execution_result,
        )
        print(
            f"TRACE worker stage=after_verifier worker={worker_name} work_id={claimed_work_id} passed={verification.passed}",
            file=sys.stderr,
        )
        current_work_item = repository.get_work_item(claimed_work_id)
        commit_result: CommitResult | None = None
        existing_commit_link = repository.get_commit_link(claimed_work_id)
        if verification.passed and committer is not None and not already_satisfied:
            if existing_commit_link is None:
                commit_result = committer(
                    current_work_item,
                    execution_result,
                    workspace_path,
                )
        result_payload_json = _build_result_payload_json(
            execution_result=execution_result,
            commit_result=commit_result,
            already_satisfied=already_satisfied,
            verification_passed=verification.passed,
        )
        approval_required = bool(result_payload_json.get("decision_required")) or (
            _extract_outcome(execution_result) == "needs_decision"
        )
        pull_request_link = _build_pull_request_link(
            work_item=current_work_item,
            result_payload_json=result_payload_json,
        )
        commit_link = _build_commit_link(
            work_item=current_work_item,
            commit_result=commit_result,
        )
        final_status, blocked_reason, final_decision_required = (
            _build_post_verification_outcome(
                verification_passed=verification.passed,
                verification_output_digest=verification.output_digest,
                approval_required=approval_required,
                session_runtime_present=session_runtime is not None,
                already_satisfied=already_satisfied,
                existing_commit_link=existing_commit_link,
                commit_result=commit_result,
                result_payload_json=result_payload_json,
            )
        )

        print(
            f"TRACE worker stage=before_finalize worker={worker_name} work_id={claimed_work_id} final_status={final_status}",
            file=sys.stderr,
        )
        repository.finalize_work_attempt(
            work_id=claimed_work_id,
            status=final_status,
            blocked_reason=blocked_reason,
            decision_required=final_decision_required,
            execution_run=ExecutionRun(
                work_id=claimed_work_id,
                worker_name=worker_name,
                status=final_status,
                branch_name=claim_branch_name_by_work_id.get(claimed_work_id),
                command_digest=execution_result.command_digest,
                summary=execution_result.summary,
                exit_code=execution_result.exit_code,
                elapsed_ms=execution_result.elapsed_ms,
                stdout_digest=execution_result.stdout_digest,
                stderr_digest=execution_result.stderr_digest,
                result_payload_json=result_payload_json or None,
            ),
            verification=verification,
            commit_link=commit_link,
            pull_request_link=pull_request_link,
        )
        if final_status == "awaiting_approval":
            repository.record_approval_event(
                ApprovalEvent(
                    work_id=claimed_work_id,
                    approver="system",
                    decision="requested",
                    reason=str(result_payload_json.get("reason_code") or "") or None,
                )
            )
        if dsn:
            _log_event(
                dsn=dsn,
                event_type="task_verified" if verification.passed else "task_blocked",
                work_id=claimed_work_id,
                actor=worker_name,
                detail={"final_status": final_status, "passed": verification.passed},
            )
            if final_status == "done":
                _log_event(
                    dsn=dsn,
                    event_type="task_completed",
                    work_id=claimed_work_id,
                    actor=worker_name,
                    detail={
                        "commit_sha": (
                            commit_result.commit_sha if commit_result else None
                        )
                    },
                )
        _write_back_task_issue_status(
            repository=repository,
            work_id=claimed_work_id,
            status=final_status,
            decision_required=final_decision_required,
            github_writeback=github_writeback,
        )
        return WorkerCycleResult(claimed_work_id=claimed_work_id)
    finally:
        if workspace_manager is not None:
            workspace_manager.release(
                work_item=repository.get_work_item(claimed_work_id),
                repository=repository,
            )


def _best_effort_prewarm_story_workspaces(
    *,
    workspace_manager: WorkspaceAdapter,
    work_items_by_id: dict[str, WorkItem],
    executable_ids: list[str],
    worker_name: str,
) -> None:
    prewarm = getattr(workspace_manager, "prewarm", None)
    if not callable(prewarm):
        return
    candidates = [
        work_items_by_id[work_id]
        for work_id in executable_ids
        if work_id in work_items_by_id
        and work_items_by_id[work_id].canonical_story_issue_number is not None
    ]
    if not candidates:
        return
    try:
        print(
            f"TRACE worker stage=before_prewarm worker={worker_name} story_candidates={len(candidates)}",
            file=sys.stderr,
        )
        prewarm(work_items=candidates)
        print(
            f"TRACE worker stage=after_prewarm worker={worker_name} story_candidates={len(candidates)}",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"TRACE worker stage=prewarm_failed worker={worker_name} error={exc}",
            file=sys.stderr,
        )


def _coerce_session_runtime(
    session_runtime: WorkerSessionRuntime | SessionManagerProtocol | bool | None,
) -> WorkerSessionRuntime | None:
    return coerce_session_runtime_adapter(
        session_runtime,
        max_iterations=DEFAULT_SESSION_MAX_ITERATIONS,
    )


def _build_worker_resume_context_builder(
    *,
    dsn: str | None,
    session_manager: SessionManagerProtocol,
) -> Callable[[ExecutionSession], str] | None:
    return build_store_backed_resume_context_builder(
        dsn=dsn,
        session_manager=session_manager,
    )


def _run_executor_with_optional_session_runtime(
    *,
    executor: ExecutorAdapter,
    repository: WorkerRepository,
    work_id: str,
    work_item: WorkItem,
    workspace_path: Path | None,
    execution_context: ExecutionContext,
    session_runtime: WorkerSessionRuntime | SessionManagerProtocol | bool | None,
    dsn: str | None,
) -> ExecutionResult:
    runtime = _coerce_session_runtime(session_runtime)
    if runtime is None:
        return _run_executor_with_heartbeat(
            executor=executor,
            repository=repository,
            work_id=work_id,
            work_item=work_item,
            workspace_path=workspace_path,
            execution_context=execution_context,
        )

    session_manager = runtime.session_manager
    resume_context_builder = (
        runtime.resume_context_builder
        or _build_worker_resume_context_builder(
            dsn=dsn,
            session_manager=session_manager,
        )
    )
    active_sessions = []
    if hasattr(session_manager, "list_active_sessions_for_work"):
        active_sessions = session_manager.list_active_sessions_for_work(work_id)
    if active_sessions:
        session = active_sessions[0]
    else:
        session = session_manager.create_session(
            work_id=work_id,
            current_phase="planning",
            context_summary=execution_context.resume_context,
            attempt_index=max(1, work_item.attempt_count + 1),
        )

    last_execution_result: ExecutionResult | None = None

    class WorkItemSessionExecutor:
        def run_turn(self, request: SessionTurnRequest) -> SessionExecutorResult:
            nonlocal last_execution_result
            turn_execution_context = replace(
                execution_context,
                session_policy=(
                    "resume_candidate" if request.resume_context else "fresh_session"
                ),
                resume_hint=request.current_phase,
                resume_context=request.resume_context
                or execution_context.resume_context,
            )
            result = _run_executor_with_heartbeat(
                executor=executor,
                repository=repository,
                work_id=work_item.id,
                work_item=work_item,
                workspace_path=workspace_path,
                execution_context=turn_execution_context,
            )
            payload = _build_session_payload(
                work_item=work_item,
                execution_result=result,
                context_summary=request.resume_context,
            )
            last_execution_result = replace(result, result_payload_json=payload)
            return SessionExecutorResult(
                success=result.success,
                payload=payload,
                exit_code=result.exit_code or 0,
            )

    completion = run_session_to_completion(
        session_id=session.id,
        session_manager=session_manager,
        wakeup_dispatcher=runtime.wakeup_dispatcher,
        executor_fn=WorkItemSessionExecutor(),
        resume_context_builder=resume_context_builder,
        policy_engine_fn=evaluate_policy,
        max_iterations=runtime.max_iterations,
        wait_fn=None if runtime.allow_wait_suspension else lambda **kwargs: True,
    )
    return _materialize_session_result(
        completion=completion,
        last_execution_result=last_execution_result,
    )


def _build_session_payload(
    *,
    work_item: WorkItem,
    execution_result: ExecutionResult,
    context_summary: str,
) -> dict[str, Any]:
    payload = dict(execution_result.result_payload_json or {})
    if not payload:
        if execution_result.success:
            payload = {
                "outcome": "done",
                "summary": execution_result.summary,
            }
        else:
            payload = {
                "outcome": "blocked",
                "summary": execution_result.summary,
                "reason_code": execution_result.blocked_reason or "executor_failure",
                "decision_required": execution_result.decision_required,
            }
    outcome = str(payload.get("outcome") or "").strip().lower()
    if outcome != "needs_decision":
        return payload

    decision = AIDecisionAgent().evaluate_needs_decision(
        work_item=work_item,
        execution_result=payload,
        context_summary=context_summary,
    )
    if decision.outcome in {
        DecisionOutcome.AUTO_RESOLVABLE,
        DecisionOutcome.RETRY_WITH_CONTEXT,
    }:
        retry_prompt = decision.retry_prompt_template or decision.suggested_action
        return {
            "execution_kind": "retry_intent",
            "failure_reason": str(payload.get("reason_code") or "needs_decision"),
            "summary": decision.reasoning,
            "retry_prompt_template": retry_prompt,
            "resume_hint": retry_prompt,
        }
    if decision.outcome == DecisionOutcome.ESCALATE_TO_OPERATOR:
        return {
            **payload,
            "decision_required": True,
            "summary": decision.reasoning,
        }
    return {
        **payload,
        "decision_required": True,
        "summary": decision.reasoning,
    }


def _materialize_session_result(
    *,
    completion: Any,
    last_execution_result: ExecutionResult | None,
) -> ExecutionResult:
    if last_execution_result is None:
        return ExecutionResult(
            success=False,
            summary="executor session produced no result",
            blocked_reason="missing-session-result",
            result_payload_json={
                "outcome": "blocked",
                "summary": "executor session produced no result",
                "reason_code": "missing-session-result",
                "decision_required": False,
            },
        )
    if completion.final_status == "completed":
        return last_execution_result

    payload = dict(last_execution_result.result_payload_json or {})
    checkpoint = completion.result.checkpoint if completion.result is not None else None
    if not payload:
        payload = {
            "outcome": "blocked",
            "summary": checkpoint.summary
            if checkpoint is not None
            else "executor session blocked",
            "reason_code": "session-runtime-blocked",
            "decision_required": completion.final_status == "human_required",
        }
    else:
        payload.setdefault("outcome", "blocked")
        payload.setdefault(
            "summary",
            checkpoint.summary
            if checkpoint is not None
            else last_execution_result.summary,
        )
        payload.setdefault(
            "reason_code",
            "human_required"
            if completion.final_status == "human_required"
            else "session-runtime-blocked",
        )
        payload["decision_required"] = completion.final_status == "human_required"

    blocked_reason = str(payload.get("reason_code") or "session-runtime-blocked")
    if completion.final_status in SESSION_WAITING_STATUSES:
        blocked_reason = str(payload.get("reason_code") or "session-waiting")
    return replace(
        last_execution_result,
        success=False,
        summary=str(payload.get("summary") or last_execution_result.summary),
        blocked_reason=blocked_reason,
        decision_required=bool(payload.get("decision_required")),
        result_payload_json=payload,
    )


def _extract_outcome(execution_result: ExecutionResult) -> str | None:
    payload = execution_result.result_payload_json or {}
    outcome = payload.get("outcome")
    if not isinstance(outcome, str):
        return None
    normalized = outcome.strip().lower()
    return normalized or None


def _build_result_payload_json(
    *,
    execution_result: ExecutionResult,
    commit_result: CommitResult | None,
    already_satisfied: bool,
    verification_passed: bool,
) -> dict[str, Any]:
    result_payload_json = dict(execution_result.result_payload_json or {})
    if commit_result is not None:
        result_payload_json["commit"] = {
            "committed": commit_result.committed,
            "commit_sha": commit_result.commit_sha,
            "commit_message": commit_result.commit_message,
            "summary": commit_result.summary,
            "blocked_reason": commit_result.blocked_reason,
        }
    if already_satisfied and verification_passed:
        result_payload_json["completion_mode"] = "preexisting_state"
    return result_payload_json


def _build_pull_request_link(
    *,
    work_item: WorkItem,
    result_payload_json: dict[str, Any],
) -> dict[str, Any] | None:
    pull_request_payload = result_payload_json.get("pull_request")
    if (
        not isinstance(pull_request_payload, dict)
        or work_item.source_issue_number is None
        or work_item.repo is None
    ):
        return None
    pull_number = pull_request_payload.get("pull_number")
    pull_url = pull_request_payload.get("pull_url")
    if not isinstance(pull_number, int) or not isinstance(pull_url, str):
        return None
    return {
        "work_id": work_item.id,
        "repo": work_item.repo,
        "issue_number": work_item.source_issue_number,
        "pull_number": pull_number,
        "pull_url": pull_url,
    }


def _build_commit_link(
    *,
    work_item: WorkItem,
    commit_result: CommitResult | None,
) -> dict[str, Any] | None:
    if (
        commit_result is None
        or not commit_result.committed
        or commit_result.commit_sha is None
        or commit_result.commit_message is None
        or work_item.source_issue_number is None
        or work_item.repo is None
    ):
        return None
    return {
        "work_id": work_item.id,
        "repo": work_item.repo,
        "issue_number": work_item.source_issue_number,
        "commit_sha": commit_result.commit_sha,
        "commit_message": commit_result.commit_message,
    }


def _build_post_verification_outcome(
    *,
    verification_passed: bool,
    verification_output_digest: str,
    approval_required: bool,
    session_runtime_present: bool,
    already_satisfied: bool,
    existing_commit_link: dict[str, Any] | None,
    commit_result: CommitResult | None,
    result_payload_json: dict[str, Any] | None = None,
) -> tuple[WorkStatus, str | None, bool]:
    final_status: WorkStatus = "done" if verification_passed else "blocked"
    blocked_reason = None if verification_passed else verification_output_digest
    final_decision_required = approval_required

    if verification_passed:
        if classify_execution_payload(result_payload_json or {}) in {
            "checkpoint",
            "wait",
            "retry_intent",
        }:
            return ("pending", None, final_decision_required)
        if existing_commit_link is not None and not already_satisfied:
            return ("blocked", "duplicate_canonical_commit", final_decision_required)
        if commit_result is not None:
            if commit_result.blocked_reason:
                return (
                    "blocked",
                    commit_result.blocked_reason,
                    final_decision_required,
                )
            if not commit_result.committed:
                return ("blocked", "missing_commit_evidence", final_decision_required)
        if approval_required and not session_runtime_present:
            return ("awaiting_approval", None, final_decision_required)

    return (final_status, blocked_reason, final_decision_required)


def _build_failure_finalization(
    *,
    claimed_work_id: str,
    worker_name: str,
    execution_result: ExecutionResult,
    current_attempt_count: int,
    branch_name: str | None,
) -> dict[str, Any]:
    continuation_kind = classify_execution_payload(
        execution_result.result_payload_json or {}
    )
    if continuation_kind in {"checkpoint", "wait", "retry_intent"}:
        payload = execution_result.result_payload_json or {}
        failure_status: WorkStatus = "pending"
        execution_run = ExecutionRun(
            work_id=claimed_work_id,
            worker_name=worker_name,
            status=failure_status,
            branch_name=branch_name,
            command_digest=execution_result.command_digest,
            summary=execution_result.summary,
            exit_code=execution_result.exit_code,
            elapsed_ms=execution_result.elapsed_ms,
            stdout_digest=execution_result.stdout_digest,
            stderr_digest=execution_result.stderr_digest,
            result_payload_json=execution_result.result_payload_json,
        )
        return {
            "status": failure_status,
            "blocked_reason": None,
            "decision_required": False,
            "attempt_count": current_attempt_count,
            "last_failure_reason": None,
            "next_eligible_at": payload.get("wake_after") or payload.get("scheduled_at"),
            "execution_run": execution_run,
        }

    (
        failure_status,
        blocked_reason,
        decision_required,
        attempt_count_delta,
        last_failure_reason,
        next_eligible_at,
        _resume_hint,
    ) = _classify_execution_failure(
        execution_result,
        attempt_count=current_attempt_count + 1,
    )
    new_attempt_count = (
        current_attempt_count + attempt_count_delta
        if attempt_count_delta is not None
        else current_attempt_count
    )
    execution_run = ExecutionRun(
        work_id=claimed_work_id,
        worker_name=worker_name,
        status="blocked",
        branch_name=branch_name,
        command_digest=execution_result.command_digest,
        summary=execution_result.summary,
        exit_code=execution_result.exit_code,
        elapsed_ms=execution_result.elapsed_ms,
        stdout_digest=execution_result.stdout_digest,
        stderr_digest=execution_result.stderr_digest,
        result_payload_json=execution_result.result_payload_json,
    )
    return {
        "status": failure_status,
        "blocked_reason": blocked_reason,
        "decision_required": decision_required,
        "attempt_count": new_attempt_count,
        "last_failure_reason": last_failure_reason,
        "next_eligible_at": next_eligible_at,
        "execution_run": execution_run,
    }


def _extract_changed_paths(result_payload_json: dict[str, Any] | None) -> list[str]:
    payload_changed_paths = (result_payload_json or {}).get("changed_paths")
    if not isinstance(payload_changed_paths, list):
        return []
    return [
        path for path in payload_changed_paths if isinstance(path, str) and path.strip()
    ]


@contextmanager
def _scoped_execution_changed_paths(result_payload_json: dict[str, Any] | None):
    previous_changed_paths = os.environ.get("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON")
    changed_paths = _extract_changed_paths(result_payload_json)
    if changed_paths:
        os.environ["TASKPLANE_EXECUTION_CHANGED_PATHS_JSON"] = json.dumps(
            changed_paths,
            ensure_ascii=False,
        )
    else:
        os.environ.pop("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON", None)
    try:
        yield changed_paths
    finally:
        if previous_changed_paths is None:
            os.environ.pop("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON", None)
        else:
            os.environ["TASKPLANE_EXECUTION_CHANGED_PATHS_JSON"] = (
                previous_changed_paths
            )


def _run_verifier_for_execution_result(
    *,
    verifier: VerifierAdapter,
    work_item: WorkItem,
    workspace_path: Path | None,
    execution_context: ExecutionContext,
    execution_result: ExecutionResult,
) -> VerificationEvidence:
    with _scoped_execution_changed_paths(execution_result.result_payload_json):
        return _run_verifier_with_context(
            verifier=verifier,
            work_item=work_item,
            workspace_path=workspace_path,
            execution_context=execution_context,
        )


def _write_back_task_issue_status(
    *,
    repository: WorkerRepository,
    work_id: str,
    status: WorkStatus,
    decision_required: bool,
    github_writeback: TaskWritebackAdapter | None,
) -> None:
    if github_writeback is None:
        return
    work_item = repository.get_work_item(work_id)
    if work_item.repo is None or work_item.source_issue_number is None:
        return
    if status not in {"done", "blocked"}:
        return
    invoke_task_writeback(
        github_writeback,
        repo=work_item.repo,
        issue_number=work_item.source_issue_number,
        status=status,
        decision_required=decision_required,
    )
