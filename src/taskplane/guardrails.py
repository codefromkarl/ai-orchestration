from __future__ import annotations

from .models import (
    ExecutionGuardrailContext,
    GuardrailViolation,
    WorkItem,
    WorkTarget,
)


def evaluate_execution_guardrails(
    work_item: WorkItem,
    targets: list[WorkTarget],
    context: ExecutionGuardrailContext,
) -> list[GuardrailViolation]:
    violations: list[GuardrailViolation] = []

    if context.allowed_waves and work_item.wave not in context.allowed_waves:
        violations.append(
            GuardrailViolation(
                code="wave-not-allowed",
                target_path="*",
                message=f"work item {work_item.id} is outside the allowed wave set",
            )
        )

    for target in targets:
        if target.owner_lane != work_item.lane:
            violations.append(
                GuardrailViolation(
                    code="owner-lane-conflict",
                    target_path=target.target_path,
                    message=(
                        f"target {target.target_path} belongs to {target.owner_lane}, "
                        f"but work item lane is {work_item.lane}"
                    ),
                )
            )
        if target.is_frozen or target.target_path.startswith(context.frozen_prefixes):
            violations.append(
                GuardrailViolation(
                    code="frozen-target",
                    target_path=target.target_path,
                    message=f"target {target.target_path} is frozen",
                )
            )
        if target.requires_human_approval or target.is_frozen:
            violations.append(
                GuardrailViolation(
                    code="human-approval-required",
                    target_path=target.target_path,
                    message=f"target {target.target_path} requires human approval",
                )
            )

    return _deduplicate_violations(violations)


def _deduplicate_violations(
    violations: list[GuardrailViolation],
) -> list[GuardrailViolation]:
    ordered: list[GuardrailViolation] = []
    seen: set[tuple[str, str]] = set()
    for violation in violations:
        key = (violation.code, violation.target_path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(violation)
    return ordered
