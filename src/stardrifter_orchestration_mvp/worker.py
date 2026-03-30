from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from typing import Callable
import sys

from ._worker_failure_policy import (
    _classify_execution_failure,
)
from ._worker_execution_context import (
    _build_execution_context,
    _run_verifier_with_context,
)
from ._worker_execution_runtime import (
    _renew_claim_after_prepare,
    _run_executor_with_heartbeat,
)
from ._worker_queue_preparation import (
    PreflightEarlyExit,
    _exclude_previously_completed_in_memory_candidates,
    _materialize_blocked_items,
    _prepare_worker_queue,
    _run_preflight_checks,
)
from .git_committer import CommitResult
from .models import (
    ApprovalEvent,
    ExecutionContext,
    ExecutionGuardrailContext,
    ExecutionRun,
    VerificationEvidence,
    WorkClaim,
    WorkItem,
    WorkStatus,
)
from .protocols import (
    ExecutorAdapter,
    TaskWritebackAdapter,
    VerifierAdapter,
    WorkspaceAdapter,
)
from .repository import ControlPlaneRepository
from .workspace import build_workspace_spec

ALREADY_SATISFIED_OUTCOME = "already_satisfied"
NON_BLOCKING_COMMIT_REASONS = {"unsafe_auto_commit_dirty_paths"}


REQUEUEABLE_BACKOFF = timedelta(minutes=5)  # 保留向后兼容


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


def run_worker_cycle(
    *,
    repository: ControlPlaneRepository,
    context: ExecutionGuardrailContext,
    worker_name: str,
    executor: ExecutorAdapter,
    verifier: VerifierAdapter,
    committer: Callable[[WorkItem, ExecutionResult, Path | None], CommitResult]
    | None = None,
    github_writeback: TaskWritebackAdapter | None = None,
    work_item_ids: list[str] | None = None,
    workspace_manager: WorkspaceAdapter | None = None,
    session_runtime: Any | None = None,
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
        execution_result = _run_executor_with_heartbeat(
            executor=executor,
            repository=repository,
            work_id=claimed_work_id,
            work_item=work_item,
            workspace_path=workspace_path,
            execution_context=execution_context,
        )
        print(
            f"TRACE worker stage=after_executor worker={worker_name} work_id={claimed_work_id} success={execution_result.success}",
            file=sys.stderr,
        )
        if not execution_result.success:
            # 传入当前 attempt_count 用于计算 backoff
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
                attempt_count=work_item.attempt_count + 1,
            )
            # 只有可恢复的错误才增加 attempt_count
            new_attempt_count = (
                work_item.attempt_count + attempt_count_delta
                if attempt_count_delta is not None
                else work_item.attempt_count
            )
            repository.finalize_work_attempt(
                work_id=claimed_work_id,
                status=failure_status,
                blocked_reason=blocked_reason,
                decision_required=decision_required,
                execution_run=ExecutionRun(
                    work_id=claimed_work_id,
                    worker_name=worker_name,
                    status="blocked",
                    branch_name=claim_branch_name_by_work_id.get(claimed_work_id),
                    command_digest=execution_result.command_digest,
                    summary=execution_result.summary,
                    exit_code=execution_result.exit_code,
                    elapsed_ms=execution_result.elapsed_ms,
                    stdout_digest=execution_result.stdout_digest,
                    stderr_digest=execution_result.stderr_digest,
                    result_payload_json=execution_result.result_payload_json,
                ),
                attempt_count=new_attempt_count,
                last_failure_reason=last_failure_reason,
                next_eligible_at=next_eligible_at,
            )
            _write_back_task_issue_status(
                repository=repository,
                work_id=claimed_work_id,
                status=failure_status,
                decision_required=decision_required,
                github_writeback=github_writeback,
            )
            return WorkerCycleResult(claimed_work_id=claimed_work_id)

        outcome = _extract_outcome(execution_result)
        if outcome == ALREADY_SATISFIED_OUTCOME:
            repository.finalize_work_attempt(
                work_id=claimed_work_id,
                status="done",
                execution_run=ExecutionRun(
                    work_id=claimed_work_id,
                    worker_name=worker_name,
                    status="done",
                    branch_name=claim_branch_name_by_work_id.get(claimed_work_id),
                    command_digest=execution_result.command_digest,
                    summary=execution_result.summary,
                    exit_code=execution_result.exit_code,
                    elapsed_ms=execution_result.elapsed_ms,
                    stdout_digest=execution_result.stdout_digest,
                    stderr_digest=execution_result.stderr_digest,
                    result_payload_json=execution_result.result_payload_json,
                ),
            )
            _write_back_task_issue_status(
                repository=repository,
                work_id=claimed_work_id,
                status="done",
                decision_required=False,
                github_writeback=github_writeback,
            )
            return WorkerCycleResult(claimed_work_id=claimed_work_id)

        repository.update_work_status(claimed_work_id, "verifying")
        print(
            f"TRACE worker stage=before_verifier worker={worker_name} work_id={claimed_work_id}",
            file=sys.stderr,
        )
        verification = _run_verifier_with_context(
            verifier=verifier,
            work_item=repository.get_work_item(claimed_work_id),
            workspace_path=workspace_path,
            execution_context=execution_context,
        )
        print(
            f"TRACE worker stage=after_verifier worker={worker_name} work_id={claimed_work_id} passed={verification.passed}",
            file=sys.stderr,
        )
        commit_result: CommitResult | None = None
        final_status = "done" if verification.passed else "blocked"
        blocked_reason = None if verification.passed else verification.output_digest
        if verification.passed and committer is not None:
            existing_commit_link = repository.get_commit_link(claimed_work_id)
            if existing_commit_link is not None:
                final_status = "blocked"
                blocked_reason = "duplicate_canonical_commit"
            else:
                commit_result = committer(
                    repository.get_work_item(claimed_work_id),
                    execution_result,
                    workspace_path,
                )
                if commit_result.blocked_reason:
                    if commit_result.blocked_reason in NON_BLOCKING_COMMIT_REASONS:
                        final_status = "done"
                        blocked_reason = None
                    else:
                        final_status = "blocked"
                        blocked_reason = commit_result.blocked_reason
        result_payload_json = dict(execution_result.result_payload_json or {})
        approval_required = bool(result_payload_json.get("decision_required")) or (
            _extract_outcome(execution_result) == "needs_decision"
        )
        if commit_result is not None:
            result_payload_json["commit"] = {
                "committed": commit_result.committed,
                "commit_sha": commit_result.commit_sha,
                "commit_message": commit_result.commit_message,
                "summary": commit_result.summary,
                "blocked_reason": commit_result.blocked_reason,
            }
        pull_request_link: dict[str, Any] | None = None
        pull_request_payload = result_payload_json.get("pull_request")
        if (
            isinstance(pull_request_payload, dict)
            and repository.get_work_item(claimed_work_id).source_issue_number
            is not None
            and repository.get_work_item(claimed_work_id).repo is not None
        ):
            pull_number = pull_request_payload.get("pull_number")
            pull_url = pull_request_payload.get("pull_url")
            if isinstance(pull_number, int) and isinstance(pull_url, str):
                pull_request_link = {
                    "work_id": claimed_work_id,
                    "repo": repository.get_work_item(claimed_work_id).repo or "",
                    "issue_number": repository.get_work_item(
                        claimed_work_id
                    ).source_issue_number
                    or 0,
                    "pull_number": pull_number,
                    "pull_url": pull_url,
                }
        commit_link: dict[str, Any] | None = None
        if (
            commit_result is not None
            and commit_result.committed
            and commit_result.commit_sha is not None
            and commit_result.commit_message is not None
            and repository.get_work_item(claimed_work_id).source_issue_number
            is not None
            and repository.get_work_item(claimed_work_id).repo is not None
        ):
            commit_link = {
                "work_id": claimed_work_id,
                "repo": repository.get_work_item(claimed_work_id).repo or "",
                "issue_number": repository.get_work_item(
                    claimed_work_id
                ).source_issue_number
                or 0,
                "commit_sha": commit_result.commit_sha,
                "commit_message": commit_result.commit_message,
            }
        final_decision_required = approval_required
        if verification.passed and approval_required and session_runtime is None:
            final_status = "awaiting_approval"
            blocked_reason = None

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


def _extract_outcome(execution_result: ExecutionResult) -> str | None:
    payload = execution_result.result_payload_json or {}
    outcome = payload.get("outcome")
    if not isinstance(outcome, str):
        return None
    normalized = outcome.strip().lower()
    return normalized or None


def _write_back_task_issue_status(
    *,
    repository: ControlPlaneRepository,
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
    github_writeback(
        repo=work_item.repo,
        issue_number=work_item.source_issue_number,
        status=status,
        decision_required=decision_required,
    )
