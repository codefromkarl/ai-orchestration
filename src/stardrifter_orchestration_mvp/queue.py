from __future__ import annotations

from datetime import UTC, datetime

from .guardrails import evaluate_execution_guardrails
from .models import (
    ExecutionGuardrailContext,
    QueueEvaluation,
    WorkClaim,
    WorkDependency,
    WorkItem,
    WorkTarget,
    GuardrailViolation,
)
from .planner import derive_ready_work_ids


def evaluate_work_queue(
    *,
    work_items: list[WorkItem],
    dependencies: list[WorkDependency],
    targets_by_work_id: dict[str, list[WorkTarget]],
    context: ExecutionGuardrailContext,
    active_claims: list[WorkClaim] | None = None,
) -> QueueEvaluation:
    item_by_id = {item.id: item for item in work_items}
    already_ready_ids = {item.id for item in work_items if item.status == "ready"}
    ready_ids = sorted(
        already_ready_ids | derive_ready_work_ids(work_items, dependencies)
    )
    active_claims = active_claims or []

    executable_ids: list[str] = []
    blocked_by_id: dict[str, list] = {}

    for work_id in ready_ids:
        work_item = item_by_id[work_id]
        targets = targets_by_work_id.get(work_id, [])
        violations = evaluate_execution_guardrails(work_item, targets, context)
        if not violations and has_path_conflict(work_item, active_claims):
            violations = [
                GuardrailViolation(
                    code="path-conflict",
                    target_path=path,
                    message=f"planned path conflicts with an active claim: {path}",
                )
                for path in work_item.planned_paths
            ] or [
                GuardrailViolation(
                    code="path-conflict",
                    target_path="*",
                    message="planned paths conflict with an active claim",
                )
            ]
        if violations:
            blocked_by_id[work_id] = violations
            continue
        executable_ids.append(work_id)

    return QueueEvaluation(
        executable_ids=executable_ids,
        blocked_by_id=blocked_by_id,
    )


def has_path_conflict(work_item: WorkItem, active_claims: list[WorkClaim]) -> bool:
    for planned_path in work_item.planned_paths:
        for claim in active_claims:
            if not _is_claim_active(claim):
                continue
            for claimed_path in claim.claimed_paths:
                if paths_conflict(planned_path, claimed_path):
                    return True
    return False


def paths_conflict(left: str, right: str) -> bool:
    normalized_left = left.rstrip("/")
    normalized_right = right.rstrip("/")
    return (
        normalized_left == normalized_right
        or normalized_left.startswith(normalized_right + "/")
        or normalized_right.startswith(normalized_left + "/")
    )


def _is_claim_active(claim: WorkClaim) -> bool:
    if claim.lease_expires_at is None:
        return True
    try:
        expires_at = datetime.fromisoformat(claim.lease_expires_at)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)
