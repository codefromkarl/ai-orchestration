from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ExecutionCheckpoint, ExecutionSession


@dataclass(frozen=True)
class PolicyResolution:
    resolution: str
    risk_level: str
    reason: str
    detail: dict[str, Any] | None = None


_HUMAN_REQUIRED_KEYWORDS = (
    "approve",
    "permission",
    "credential",
    "secret",
    "security",
    "deploy",
    "production",
    "审批",
    "权限",
    "密钥",
    "安全",
    "部署",
    "生产",
)

_AUTO_RESOLVE_KEYWORDS = (
    "dirty tree",
    "dirty worktree",
    "workspace cleanup",
    "clean workspace",
)

_HARD_GUARDRAIL_REASON_CODES = {
    "human-approval-required",
    "frozen-target",
    "owner-lane-conflict",
    "wave-not-allowed",
}

_WORKSPACE_CONFLICT_PREFIXES = (
    "path-conflict:",
    "workspace-conflict:",
)

_TRANSIENT_RETRY_REASON_CODES = {
    "interrupted_retryable",
    "session-waiting",
    "tool-result-pending",
    "subagent-result-pending",
}


def evaluate_policy(
    *,
    session: ExecutionSession,
    checkpoint: ExecutionCheckpoint | None,
    failure_context: dict[str, Any] | None,
    attempt_index: int,
) -> PolicyResolution:
    if failure_context is None:
        failure_context = {}
    outcome = str(failure_context.get("outcome") or "").strip().lower()
    reason_code = str(failure_context.get("reason_code") or "").strip().lower()
    summary = str(failure_context.get("summary") or "").strip().lower()
    blocked_reason = str(failure_context.get("blocked_reason") or "").strip().lower()
    combined = f"{outcome} {reason_code} {summary} {blocked_reason}"

    if reason_code in _HARD_GUARDRAIL_REASON_CODES:
        return PolicyResolution(
            resolution="human_required",
            risk_level="high",
            reason=f"Hard guardrail stop: {reason_code}",
            detail={"reason_class": "guardrail_hard_stop"},
        )

    for prefix in _WORKSPACE_CONFLICT_PREFIXES:
        if reason_code.startswith(prefix):
            return PolicyResolution(
                resolution="auto_resolve",
                risk_level="low",
                reason=f"Workspace conflict is auto-resolvable: {reason_code}",
                detail={
                    "reason_class": "workspace_conflict",
                    "matched_prefix": prefix,
                },
            )

    if reason_code in _TRANSIENT_RETRY_REASON_CODES:
        return PolicyResolution(
            resolution="retry_strategy",
            risk_level="low",
            reason=f"Transient executor failure: {reason_code}",
            detail={
                "reason_class": "transient_executor_failure",
                "strategy": "retry_fresh",
            },
        )

    for kw in _HUMAN_REQUIRED_KEYWORDS:
        if kw in combined:
            return PolicyResolution(
                resolution="human_required",
                risk_level="high",
                reason=f"Contains human-required keyword: {kw}",
                detail={"matched_keyword": kw},
            )

    for kw in _AUTO_RESOLVE_KEYWORDS:
        if kw in combined:
            return PolicyResolution(
                resolution="auto_resolve",
                risk_level="low",
                reason=f"Known auto-resolvable condition: {kw}",
                detail={"matched_keyword": kw},
            )

    if outcome == "needs_decision":
        if attempt_index < 3:
            return PolicyResolution(
                resolution="retry_strategy",
                risk_level="medium",
                reason="needs_decision with low attempt count",
                detail={"strategy": "retry_with_narrowed_scope"},
            )
        return PolicyResolution(
            resolution="human_required",
            risk_level="high",
            reason="needs_decision after multiple attempts",
            detail={"attempt_index": attempt_index},
        )

    if reason_code == "timeout" or "timeout" in combined:
        if attempt_index < 5:
            return PolicyResolution(
                resolution="retry_strategy",
                risk_level="low",
                reason="timeout is retryable",
                detail={"strategy": "retry_fresh"},
            )
        return PolicyResolution(
            resolution="human_required",
            risk_level="high",
            reason="timeout after many attempts",
            detail={"attempt_index": attempt_index},
        )

    if "verifier" in combined or "test" in combined:
        if attempt_index < 3:
            return PolicyResolution(
                resolution="retry_strategy",
                risk_level="medium",
                reason="verifier failure may be retryable",
                detail={"strategy": "diagnose_then_retry"},
            )
        return PolicyResolution(
            resolution="human_required",
            risk_level="high",
            reason="verifier failure after multiple attempts",
        )

    if attempt_index < 3:
        return PolicyResolution(
            resolution="retry_strategy",
            risk_level="medium",
            reason="default retry for non-specific failure",
            detail={"strategy": "retry_fresh"},
        )

    return PolicyResolution(
        resolution="human_required",
        risk_level="high",
        reason="exceeded retry threshold",
        detail={"attempt_index": attempt_index},
    )
