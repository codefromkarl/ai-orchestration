from stardrifter_orchestration_mvp.models import (
    ExecutionGuardrailContext,
    WorkClaim,
    WorkDependency,
    WorkItem,
    WorkTarget,
)
from stardrifter_orchestration_mvp.queue import evaluate_work_queue


def test_evaluate_work_queue_separates_executable_and_blocked_ready_items():
    work_items = [
        WorkItem(
            id="task-1", title="upstream", lane="Lane 06", wave="wave-5", status="done"
        ),
        WorkItem(
            id="task-2",
            title="safe cleanup",
            lane="Lane 06",
            wave="wave-5",
            status="pending",
        ),
        WorkItem(
            id="task-3",
            title="needs approval",
            lane="Lane 06",
            wave="wave-5",
            status="pending",
        ),
    ]
    dependencies = [
        WorkDependency(work_id="task-2", depends_on_work_id="task-1"),
        WorkDependency(work_id="task-3", depends_on_work_id="task-1"),
    ]
    targets_by_work_id = {
        "task-2": [
            WorkTarget(
                work_id="task-2",
                target_path="src/stardrifter_engine/projections/godot_map_projection.py",
                target_type="file",
                owner_lane="Lane 06",
                is_frozen=False,
                requires_human_approval=False,
            )
        ],
        "task-3": [
            WorkTarget(
                work_id="task-3",
                target_path="docs/authority/active-baselines.md",
                target_type="doc",
                owner_lane="Lane 06",
                is_frozen=True,
                requires_human_approval=True,
            )
        ],
    }
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    evaluation = evaluate_work_queue(
        work_items=work_items,
        dependencies=dependencies,
        targets_by_work_id=targets_by_work_id,
        context=context,
    )

    assert evaluation.executable_ids == ["task-2"]
    assert set(evaluation.blocked_by_id) == {"task-3"}
    assert {item.code for item in evaluation.blocked_by_id["task-3"]} == {
        "frozen-target",
        "human-approval-required",
    }


def test_evaluate_work_queue_blocks_ready_items_when_claimed_paths_conflict():
    work_items = [
        WorkItem(
            id="task-53",
            title="[04-DOC] current edit",
            lane="Lane 04",
            wave="unassigned",
            status="pending",
            planned_paths=("docs/domains/04-encounter-mediation/execution-plan.md",),
        ),
        WorkItem(
            id="task-54",
            title="[04-DOC] overlapping edit",
            lane="Lane 04",
            wave="unassigned",
            status="pending",
            planned_paths=("docs/domains/04-encounter-mediation/README.md",),
        ),
    ]
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    claims = [
        WorkClaim(
            work_id="other-task",
            worker_name="worker-a",
            workspace_path="/tmp/worktree-53",
            branch_name="task/53",
            claimed_paths=("docs/domains/04-encounter-mediation/",),
        )
    ]

    evaluation = evaluate_work_queue(
        work_items=work_items,
        dependencies=[],
        targets_by_work_id={},
        context=context,
        active_claims=claims,
    )

    assert evaluation.executable_ids == []
    assert set(evaluation.blocked_by_id) == {"task-53", "task-54"}
    assert {item.code for item in evaluation.blocked_by_id["task-53"]} == {
        "path-conflict"
    }


def test_evaluate_work_queue_ignores_expired_claims_for_path_conflict():
    work_items = [
        WorkItem(
            id="task-53",
            title="current edit",
            lane="Lane 04",
            wave="unassigned",
            status="pending",
            planned_paths=("docs/domains/04-encounter-mediation/execution-plan.md",),
        )
    ]
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    claims = [
        WorkClaim(
            work_id="other-task",
            worker_name="worker-a",
            workspace_path="/tmp/worktree-53",
            branch_name="task/53",
            lease_token="expired-lease",
            lease_expires_at="2000-01-01T00:00:00+00:00",
            claimed_paths=("docs/domains/04-encounter-mediation/",),
        )
    ]

    evaluation = evaluate_work_queue(
        work_items=work_items,
        dependencies=[],
        targets_by_work_id={},
        context=context,
        active_claims=claims,
    )

    assert evaluation.executable_ids == ["task-53"]
    assert evaluation.blocked_by_id == {}
