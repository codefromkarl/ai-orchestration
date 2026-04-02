from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .models import WorkStatus

REQUEUEABLE_EXECUTION_FAILURE_REASONS = {
    "timeout",
    "interrupted_retryable",
    "git-lock-conflict",
    "resource_temporarily_unavailable",
}

REQUIRES_HUMAN_FAILURE_REASONS = {
    "permission_required",
    "security_concern",
    "data_loss_risk",
    "external_dependency",
    "upstream_api_error",
    "api_key_required",
    "credential_required",
}

BACKOFF_BASE_MINUTES = 5
BACKOFF_MULTIPLIER = 2.0
BACKOFF_MAX_MINUTES = 240


def calculate_backoff(attempt_count: int) -> timedelta:
    from datetime import timedelta

    backoff_minutes = min(
        BACKOFF_BASE_MINUTES * (BACKOFF_MULTIPLIER ** (attempt_count - 1)),
        BACKOFF_MAX_MINUTES,
    )
    return timedelta(minutes=int(backoff_minutes))


def is_auto_resolvable_failure(reason_code: str) -> bool:
    if reason_code in REQUEUEABLE_EXECUTION_FAILURE_REASONS:
        return True

    auto_resolvable_patterns = [
        "awaiting_user_input",
        "ask_next_step",
        "awaiting_next_step",
        "paused_for_input",
        "unclear_requirements",
        "ambiguous_task",
        "context_gathering",
        "research_in_progress",
    ]

    reason_lower = reason_code.lower()
    return any(pattern in reason_lower for pattern in auto_resolvable_patterns)


def is_human_required_failure(reason_code: str) -> bool:
    if reason_code in REQUIRES_HUMAN_FAILURE_REASONS:
        return True

    human_required_patterns = [
        "permission_required",
        "security_concern",
        "data_loss_risk",
        "external_dependency",
        "api_key_required",
        "credential_required",
    ]

    reason_lower = reason_code.lower()
    return any(pattern in reason_lower for pattern in human_required_patterns)


def _classify_execution_failure(
    execution_result: Any,
    attempt_count: int = 1,
) -> tuple[
    WorkStatus,
    str | None,
    bool,
    int | None,
    str | None,
    str | None,
    str | None,
]:
    blocked_reason = execution_result.blocked_reason or "unknown"

    if is_human_required_failure(blocked_reason):
        return (
            "blocked",
            execution_result.blocked_reason or execution_result.summary,
            True,
            None,
            blocked_reason,
            None,
            None,
        )

    if is_auto_resolvable_failure(blocked_reason):
        resume_hint = None
        next_eligible_at = None

        if blocked_reason == "interrupted_retryable":
            resume_hint = "resume_candidate"
            next_eligible_at = None
        else:
            backoff = calculate_backoff(attempt_count)
            next_eligible_at = (datetime.now(UTC) + backoff).isoformat()

        return (
            "pending",
            None,
            False,
            1,
            blocked_reason,
            next_eligible_at,
            resume_hint,
        )

    return (
        "blocked",
        execution_result.blocked_reason or execution_result.summary,
        execution_result.decision_required,
        None,
        None,
        None,
        None,
    )
