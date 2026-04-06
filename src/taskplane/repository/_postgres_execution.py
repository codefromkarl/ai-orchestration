from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ..models import ExecutionRun, VerificationEvidence, WorkStatus


def apply_finalization_status_update(
    *,
    update_work_status: Callable[..., None],
    work_id: str,
    status: WorkStatus,
    blocked_reason: str | None = None,
    decision_required: bool = False,
    attempt_count: int | None = None,
    last_failure_reason: str | None = None,
    next_eligible_at: str | None = None,
) -> None:
    update_work_status(
        work_id,
        status,
        blocked_reason=blocked_reason,
        decision_required=decision_required,
        attempt_count=attempt_count,
        last_failure_reason=last_failure_reason,
        next_eligible_at=next_eligible_at,
    )


def record_finalization_followups(
    *,
    record_run: Callable[[ExecutionRun], int | None],
    record_verification: Callable[[VerificationEvidence], None],
    record_commit_link: Callable[..., None],
    record_pull_request_link: Callable[..., None],
    execution_run: ExecutionRun,
    verification: VerificationEvidence | None = None,
    commit_link: dict[str, Any] | None = None,
    pull_request_link: dict[str, Any] | None = None,
) -> None:
    run_id = record_run(execution_run)
    if verification is not None:
        record_verification(replace(verification, run_id=run_id or verification.run_id))
    if commit_link is not None:
        record_commit_link(**commit_link)
    if pull_request_link is not None:
        record_pull_request_link(**pull_request_link)
