from taskplane._worker_queue_preparation import (
    _materialize_blocked_items,
)
from taskplane.models import (
    GuardrailViolation,
    QueueEvaluation,
    WorkItem,
)
from taskplane.repository import InMemoryControlPlaneRepository
from taskplane.schedulers import task_scheduler


def test_materialize_blocked_items_skips_transient_path_conflicts():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-1",
                title="conflicting edit",
                lane="Lane 01",
                wave="wave-1",
                status="ready",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    evaluation = QueueEvaluation(
        executable_ids=[],
        blocked_by_id={
            "task-1": [
                GuardrailViolation(
                    code="path-conflict",
                    target_path="src/conflict.py",
                    message="conflicts with active claim",
                )
            ]
        },
    )

    _materialize_blocked_items(repository, evaluation)

    assert repository.get_work_item("task-1").status == "ready"
    assert repository.blocked_reasons == {}


def test_materialize_blocked_items_persists_non_transient_violations():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-2",
                title="frozen edit",
                lane="Lane 01",
                wave="wave-1",
                status="ready",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    evaluation = QueueEvaluation(
        executable_ids=[],
        blocked_by_id={
            "task-2": [
                GuardrailViolation(
                    code="frozen-target",
                    target_path="docs/authority/policy.md",
                    message="target is frozen",
                )
            ]
        },
    )

    _materialize_blocked_items(repository, evaluation)

    assert repository.get_work_item("task-2").status == "blocked"
    assert "task-2" in repository.blocked_reasons


def test_select_task_candidates_only_estimates_conflicts_for_eligible_candidates(
    monkeypatch,
):
    observed_work_ids: list[str] = []

    def fake_estimate_conflict_counts(candidates):
        observed_work_ids.extend(row["work_id"] for row in candidates)
        return {row["work_id"]: 0 for row in candidates}

    monkeypatch.setattr(
        task_scheduler,
        "estimate_conflict_counts",
        fake_estimate_conflict_counts,
    )

    candidates = [
        {
            "work_id": "task-ready",
            "status": "ready",
            "task_type": "core_path",
            "blocking_mode": "hard",
            "canonical_story_issue_number": 11,
            "planned_paths": ["src/ready.py"],
            "source_issue_number": 11,
        },
        {
            "work_id": "task-pending",
            "status": "pending",
            "task_type": "core_path",
            "blocking_mode": "hard",
            "canonical_story_issue_number": 12,
            "planned_paths": ["src/pending.py"],
            "source_issue_number": 12,
        },
        {
            "work_id": "task-dependency-blocked",
            "status": "ready",
            "task_type": "core_path",
            "blocking_mode": "hard",
            "canonical_story_issue_number": 13,
            "planned_paths": ["src/blocked.py"],
            "source_issue_number": 13,
        },
    ]
    dependencies = [
        {
            "work_id": "task-dependency-blocked",
            "depends_on_work_id": "task-upstream",
            "dependency_blocking_mode": "hard",
            "dependency_status": "pending",
        }
    ]

    selected = task_scheduler.select_task_candidates(
        candidates=candidates,
        dependencies=dependencies,
        occupied_paths=[],
        max_parallel=4,
    )

    assert observed_work_ids == ["task-ready"]
    assert [row["work_id"] for row in selected] == ["task-ready"]
