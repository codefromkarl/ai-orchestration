"""
Helper functions for repository operations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import WorkClaim, WorkItem


def _claim_has_path_conflict(
    claimed_paths: tuple[str, ...],
    existing_claims: list[WorkClaim],
    *,
    excluding_work_id: str,
) -> bool:
    """Check if claimed paths conflict with any active work claims."""
    from ..queue import paths_conflict

    for claim in existing_claims:
        if claim.work_id == excluding_work_id:
            continue
        if not _is_claim_active(claim):
            continue
        for claimed_path in claimed_paths:
            for existing_path in claim.claimed_paths:
                if paths_conflict(claimed_path, existing_path):
                    return True
    return False


def _is_claim_active(claim: WorkClaim) -> bool:
    """Check if a work claim is currently active (not expired)."""
    if claim.lease_expires_at is None:
        return True
    try:
        expires_at = datetime.fromisoformat(claim.lease_expires_at)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)


def _is_work_item_eligible(work_item: WorkItem) -> bool:
    """Check if a work item is eligible for execution based on timing."""
    if work_item.next_eligible_at is None:
        return True
    try:
        next_eligible_at = datetime.fromisoformat(work_item.next_eligible_at)
    except ValueError:
        return True
    if next_eligible_at.tzinfo is None:
        next_eligible_at = next_eligible_at.replace(tzinfo=UTC)
    return next_eligible_at <= datetime.now(UTC)
