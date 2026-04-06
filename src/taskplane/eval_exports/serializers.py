from __future__ import annotations

from typing import Any

from ..models import ExecutionRun, VerificationEvidence, WorkItem
from .schemas import (
    ExecutionAttemptExport,
    VerificationResultExport,
    WorkSnapshotExport,
)


def serialize_work_snapshot(work_item: WorkItem) -> WorkSnapshotExport:
    return WorkSnapshotExport(
        work_id=work_item.id,
        repo=work_item.repo or "",
        title=work_item.title,
        status=work_item.status,
        lane=work_item.lane,
        wave=work_item.wave,
        task_type=work_item.task_type,
        blocking_mode=work_item.blocking_mode,
        attempt_count=work_item.attempt_count,
        last_failure_reason=work_item.last_failure_reason,
        next_eligible_at=work_item.next_eligible_at,
        decision_required=work_item.decision_required,
        blocked_reason=work_item.blocked_reason,
        source_issue_number=work_item.source_issue_number,
        canonical_story_issue_number=work_item.canonical_story_issue_number,
    )


def serialize_execution_attempt(
    run: ExecutionRun,
    *,
    run_id: int,
    attempt_number: int,
    executor_name: str | None = None,
    executor_profile: str | None = None,
    session_id: str | None = None,
    workspace_path: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> ExecutionAttemptExport:
    return ExecutionAttemptExport(
        run_id=run_id,
        work_id=run.work_id,
        attempt_number=attempt_number,
        worker_name=run.worker_name,
        status=run.status,
        executor_name=executor_name,
        executor_profile=executor_profile,
        session_id=session_id,
        branch_name=run.branch_name,
        workspace_path=workspace_path,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_ms=run.elapsed_ms,
        exit_code=run.exit_code,
        command_digest=run.command_digest,
        stdout_digest=run.stdout_digest,
        stderr_digest=run.stderr_digest,
        result_payload=run.result_payload_json,
        partial_artifacts=run.partial_artifacts,
    )


def serialize_verification_result(
    evidence: VerificationEvidence,
    *,
    attempt_number: int,
    verifier_name: str,
    verification_id: str | None = None,
    classification: dict[str, Any] | None = None,
) -> VerificationResultExport:
    effective_run_id = evidence.run_id if evidence.run_id is not None else 0
    effective_classification = classification or {
        "result": "passed" if evidence.passed else "failed"
    }
    return VerificationResultExport(
        verification_id=verification_id or f"ver-{effective_run_id}-{verifier_name}",
        run_id=effective_run_id,
        work_id=evidence.work_id,
        attempt_number=attempt_number,
        verifier_name=verifier_name,
        check_type=evidence.check_type,
        command=evidence.command,
        passed=evidence.passed,
        exit_code=evidence.exit_code,
        elapsed_ms=evidence.elapsed_ms,
        stdout_digest=evidence.stdout_digest,
        stderr_digest=evidence.stderr_digest,
        output_digest=evidence.output_digest,
        classification=effective_classification,
    )
