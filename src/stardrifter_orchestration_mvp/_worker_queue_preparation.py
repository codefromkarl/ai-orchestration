from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import sys

from .models import ExecutionRun, ExecutionGuardrailContext, QueueEvaluation, WorkItem
from .queue import evaluate_work_queue
from .repository import ControlPlaneRepository


@dataclass(frozen=True)
class WorkerQueuePreparationResult:
    early_exit_result: Any | None
    evaluation: QueueEvaluation
    work_items: list[WorkItem]


@dataclass(frozen=True)
class PreflightEarlyExit:
    claimed_work_id: str | None


def _prepare_worker_queue(
    *,
    repository: ControlPlaneRepository,
    context: ExecutionGuardrailContext,
    work_item_ids: list[str] | None,
    worker_name: str,
) -> WorkerQueuePreparationResult:
    preflight_result = _run_preflight_checks(
        repository=repository, work_item_ids=work_item_ids
    )
    if preflight_result is not None:
        return WorkerQueuePreparationResult(
            early_exit_result=preflight_result,
            evaluation=QueueEvaluation(executable_ids=[], blocked_by_id={}),
            work_items=[],
        )
    print(f"TRACE worker stage=before_sync_ready worker={worker_name}", file=sys.stderr)
    repository.sync_ready_states()
    print(f"TRACE worker stage=after_sync_ready worker={worker_name}", file=sys.stderr)
    if work_item_ids is None and hasattr(repository, "list_active_work_items"):
        work_items = repository.list_active_work_items()
    else:
        work_items = repository.list_work_items()
    if work_item_ids is not None:
        allowed_ids = set(work_item_ids)
        work_items = [item for item in work_items if item.id in allowed_ids]
    evaluation = evaluate_work_queue(
        work_items=work_items,
        dependencies=repository.list_dependencies(),
        targets_by_work_id=repository.list_targets_by_work_id(),
        context=context,
        active_claims=repository.list_active_work_claims()
        if hasattr(repository, "list_active_work_claims")
        else [],
    )
    evaluation, work_items = _exclude_previously_completed_in_memory_candidates(
        repository=repository,
        evaluation=evaluation,
        work_items=work_items,
    )
    print(
        f"TRACE worker stage=after_queue_eval worker={worker_name} executable_count={len(evaluation.executable_ids)}",
        file=sys.stderr,
    )
    _materialize_blocked_items(repository, evaluation)
    return WorkerQueuePreparationResult(
        early_exit_result=None,
        evaluation=evaluation,
        work_items=work_items,
    )


def _materialize_blocked_items(
    repository: ControlPlaneRepository,
    evaluation: QueueEvaluation,
) -> None:
    for work_id, violations in evaluation.blocked_by_id.items():
        repository.mark_blocked(work_id, violations)


def _exclude_previously_completed_in_memory_candidates(
    *,
    repository: ControlPlaneRepository,
    evaluation: QueueEvaluation,
    work_items: list[WorkItem],
) -> tuple[QueueEvaluation, list[WorkItem]]:
    execution_runs = getattr(repository, "execution_runs", None)
    if not isinstance(execution_runs, list):
        return evaluation, work_items
    completed_work_ids = {
        run.work_id
        for run in execution_runs
        if isinstance(run, ExecutionRun) and run.status == "done"
    }
    if not completed_work_ids:
        return evaluation, work_items
    filtered_executable_ids = [
        work_id
        for work_id in evaluation.executable_ids
        if work_id not in completed_work_ids
    ]
    if len(filtered_executable_ids) == len(evaluation.executable_ids):
        return evaluation, work_items
    return (
        QueueEvaluation(
            executable_ids=filtered_executable_ids,
            blocked_by_id=evaluation.blocked_by_id,
        ),
        [item for item in work_items if item.id not in completed_work_ids],
    )


def _run_preflight_checks(
    *,
    repository: ControlPlaneRepository,
    work_item_ids: list[str] | None,
) -> Any | None:
    work_items = repository.list_work_items()
    if work_item_ids is not None:
        allowed_ids = set(work_item_ids)
        work_items = [item for item in work_items if item.id in allowed_ids]
    for work_item in work_items:
        if work_item.status != "pending":
            continue
        if work_item.repo is not None and work_item.source_issue_number is None:
            repository.update_work_status(
                work_item.id,
                "blocked",
                blocked_reason="missing_source_issue_number",
                decision_required=False,
            )
            return PreflightEarlyExit(claimed_work_id=None)
    return None
