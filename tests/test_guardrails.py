from taskplane.guardrails import evaluate_execution_guardrails
from taskplane.models import (
    ExecutionGuardrailContext,
    WorkItem,
    WorkTarget,
)


def test_evaluate_execution_guardrails_flags_frozen_owner_and_approval_conflicts():
    work_item = WorkItem(
        id="task-06-c-001",
        title="cleanup strategic consumer",
        lane="Lane 06",
        wave="wave-5",
        status="ready",
        complexity="medium",
    )
    targets = [
        WorkTarget(
            work_id="task-06-c-001",
            target_path="src/stardrifter_engine/projections/godot_map_projection.py",
            target_type="file",
            owner_lane="Lane 06",
            is_frozen=False,
            requires_human_approval=False,
        ),
        WorkTarget(
            work_id="task-06-c-001",
            target_path="docs/authority/active-baselines.md",
            target_type="doc",
            owner_lane="Lane 06",
            is_frozen=True,
            requires_human_approval=True,
        ),
        WorkTarget(
            work_id="task-06-c-001",
            target_path="src/stardrifter_engine/engine/world_engine.py",
            target_type="file",
            owner_lane="Lane 02",
            is_frozen=False,
            requires_human_approval=False,
        ),
    ]
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    violations = evaluate_execution_guardrails(work_item, targets, context)
    violation_codes = {violation.code for violation in violations}

    assert violation_codes == {
        "frozen-target",
        "human-approval-required",
        "owner-lane-conflict",
    }
