from __future__ import annotations

import sys
from typing import Any, Callable

from .git_committer import CommitResult
from .models import (
    ExecutionGuardrailContext,
    StoryIntegrationRun,
    StoryPullRequestLink,
    StoryRunResult,
    StoryVerificationRun,
    VerificationEvidence,
    WorkItem,
)
from .protocols import (
    ExecutorAdapter,
    invoke_story_integrator,
    invoke_story_writeback,
    StoryIntegratorAdapter,
    StoryWritebackAdapter,
    VerifierAdapter,
    WorkspaceAdapter,
)
from .repository import StoryRepository
from .worker import ExecutionResult, run_worker_cycle


def run_story_until_settled(
    *,
    story_issue_number: int,
    story_work_item_ids: list[str],
    repository: StoryRepository,
    context: ExecutionGuardrailContext,
    worker_name: str,
    executor: ExecutorAdapter,
    verifier: VerifierAdapter,
    story_verifier: Callable[..., StoryVerificationRun] | None = None,
    committer: Callable[[WorkItem, ExecutionResult, object | None], CommitResult]
    | None = None,
    story_github_writeback: StoryWritebackAdapter | None = None,
    story_integrator: StoryIntegratorAdapter | None = None,
    workspace_manager: WorkspaceAdapter | None = None,
    max_cycles: int = 100,
    session_manager: Any | None = None,
    wakeup_dispatcher: Any | None = None,
    dsn: str | None = None,
) -> StoryRunResult:
    for cycle_index in range(max_cycles):
        print(
            f"TRACE story_runner stage=cycle_start story={story_issue_number} cycle={cycle_index}",
            file=sys.stderr,
        )
        scoped_items = [
            repository.get_work_item(work_item_id)
            for work_item_id in story_work_item_ids
            if _has_work_item(repository, work_item_id)
        ]
        if not scoped_items:
            return StoryRunResult(
                story_issue_number=story_issue_number,
                completed_work_item_ids=[],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=False,
                merge_blocked_reason=None,
            )
        completed_ids = [item.id for item in scoped_items if item.status == "done"]
        blocked_ids = [item.id for item in scoped_items if item.status == "blocked"]
        remaining_ids = [
            item.id
            for item in scoped_items
            if item.status in {"pending", "ready", "in_progress", "verifying"}
        ]
        if not remaining_ids:
            return _finalize_story_result(
                repository=repository,
                story_issue_number=story_issue_number,
                scoped_items=scoped_items,
                completed_ids=completed_ids,
                blocked_ids=blocked_ids,
                story_github_writeback=story_github_writeback,
                story_integrator=story_integrator,
                story_verifier=story_verifier,
            )

        cycle_result = run_worker_cycle(
            repository=repository,
            context=context,
            worker_name=worker_name,
            executor=executor,
            verifier=verifier,
            committer=committer,
            work_item_ids=story_work_item_ids,
            workspace_manager=workspace_manager,
            session_runtime=session_manager if session_manager is not None else True,
            dsn=dsn,
        )
        print(
            f"TRACE story_runner stage=worker_cycle_result story={story_issue_number} claimed_work_id={cycle_result.claimed_work_id}",
            file=sys.stderr,
        )
        if cycle_result.claimed_work_id is None:
            scoped_items = [
                repository.get_work_item(work_item_id)
                for work_item_id in story_work_item_ids
                if _has_work_item(repository, work_item_id)
            ]
            completed_ids = [item.id for item in scoped_items if item.status == "done"]
            blocked_ids = [item.id for item in scoped_items if item.status == "blocked"]
            remaining_ids = [
                item.id
                for item in scoped_items
                if item.status in {"pending", "ready", "in_progress", "verifying"}
            ]
            if not remaining_ids:
                return _finalize_story_result(
                    repository=repository,
                    story_issue_number=story_issue_number,
                    scoped_items=scoped_items,
                    completed_ids=completed_ids,
                    blocked_ids=blocked_ids,
                    story_github_writeback=story_github_writeback,
                    story_integrator=story_integrator,
                    story_verifier=story_verifier,
                )
            return StoryRunResult(
                story_issue_number=story_issue_number,
                completed_work_item_ids=completed_ids,
                blocked_work_item_ids=blocked_ids,
                remaining_work_item_ids=remaining_ids,
                story_complete=False,
                merge_blocked_reason=None,
            )

    scoped_items = [
        repository.get_work_item(work_item_id)
        for work_item_id in story_work_item_ids
        if _has_work_item(repository, work_item_id)
    ]
    return StoryRunResult(
        story_issue_number=story_issue_number,
        completed_work_item_ids=[
            item.id for item in scoped_items if item.status == "done"
        ],
        blocked_work_item_ids=[
            item.id for item in scoped_items if item.status == "blocked"
        ],
        remaining_work_item_ids=[
            item.id
            for item in scoped_items
            if item.status in {"pending", "ready", "in_progress", "verifying"}
        ],
        story_complete=False,
        merge_blocked_reason=None,
    )


def _finalize_story_result(
    *,
    repository: StoryRepository,
    story_issue_number: int,
    scoped_items: list[WorkItem],
    completed_ids: list[str],
    blocked_ids: list[str],
    story_github_writeback: StoryWritebackAdapter | None,
    story_integrator: StoryIntegratorAdapter | None,
    story_verifier: Callable[..., StoryVerificationRun] | None,
) -> StoryRunResult:
    print(
        f"TRACE story_runner stage=terminal_check story={story_issue_number} completed={len(completed_ids)} blocked={len(blocked_ids)}",
        file=sys.stderr,
    )
    result = StoryRunResult(
        story_issue_number=story_issue_number,
        completed_work_item_ids=completed_ids,
        blocked_work_item_ids=blocked_ids,
        remaining_work_item_ids=[],
        story_complete=len(blocked_ids) == 0
        and len(completed_ids) == len(scoped_items),
        reason_code="story_complete"
        if len(blocked_ids) == 0 and len(completed_ids) == len(scoped_items)
        else None,
    )
    merge_blocked_reason = _integrate_story_branch(
        repository=repository,
        story_issue_number=story_issue_number,
        story_work_items=scoped_items,
        story_complete=result.story_complete,
        story_integrator=story_integrator,
    )
    if merge_blocked_reason is not None:
        result = StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=completed_ids,
            blocked_work_item_ids=blocked_ids,
            remaining_work_item_ids=[],
            story_complete=False,
            merge_blocked_reason=merge_blocked_reason,
            reason_code=merge_blocked_reason,
        )
    verification_failed_reason = _verify_story_completion(
        repository=repository,
        story_issue_number=story_issue_number,
        story_work_items=scoped_items,
        story_complete=result.story_complete,
        story_verifier=story_verifier,
    )
    if verification_failed_reason is not None:
        result = StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=completed_ids,
            blocked_work_item_ids=blocked_ids,
            remaining_work_item_ids=[],
            story_complete=False,
            merge_blocked_reason=result.merge_blocked_reason,
            reason_code=verification_failed_reason,
        )
    _write_back_story_issue_status(
        repository=repository,
        story_issue_number=story_issue_number,
        story_complete=result.story_complete,
        story_github_writeback=story_github_writeback,
    )
    _write_back_story_governance_status(
        repository=repository,
        story_issue_number=story_issue_number,
        story_complete=result.story_complete,
    )
    return result


def _verify_story_completion(
    *,
    repository: StoryRepository,
    story_issue_number: int,
    story_work_items: list[WorkItem],
    story_complete: bool,
    story_verifier: Callable[..., StoryVerificationRun] | None,
) -> str | None:
    if not story_complete or story_verifier is None:
        return None
    verification_run = story_verifier(
        story_issue_number=story_issue_number,
        story_work_items=story_work_items,
    )
    if hasattr(repository, "record_story_verification_run"):
        repository.record_story_verification_run(verification_run)
    if verification_run.passed:
        return None
    story_repo = next(
        (item.repo for item in story_work_items if item.repo is not None), None
    )
    if story_repo is not None and hasattr(
        repository, "set_program_story_execution_status_with_propagation"
    ):
        repository.set_program_story_execution_status_with_propagation(
            repo=story_repo,
            issue_number=story_issue_number,
            execution_status="gated",
        )
    return "story_verification_failed"


def load_story_work_item_ids(
    *,
    repository: StoryRepository,
    story_issue_number: int,
) -> list[str]:
    if hasattr(repository, "list_story_work_item_ids"):
        return repository.list_story_work_item_ids(story_issue_number)
    matching = [
        work_item.id
        for work_item in repository.list_work_items()
        if story_issue_number in work_item.story_issue_numbers
    ]
    return sorted(matching)


def _has_work_item(repository: StoryRepository, work_item_id: str) -> bool:
    try:
        repository.get_work_item(work_item_id)
    except KeyError:
        return False
    return True


def _write_back_story_issue_status(
    *,
    repository: StoryRepository,
    story_issue_number: int,
    story_complete: bool,
    story_github_writeback: StoryWritebackAdapter | None,
) -> None:
    if story_github_writeback is None or not story_complete:
        return
    story_items = [
        item
        for item in repository.list_work_items()
        if item.canonical_story_issue_number == story_issue_number
        or story_issue_number in item.story_issue_numbers
    ]
    story_repo = next(
        (item.repo for item in story_items if item.repo is not None), None
    )
    if story_repo is None:
        return
    invoke_story_writeback(
        story_github_writeback,
        repo=story_repo,
        issue_number=story_issue_number,
        status="done",
        decision_required=False,
    )


def _write_back_story_governance_status(
    *,
    repository: StoryRepository,
    story_issue_number: int,
    story_complete: bool,
) -> None:
    if not story_complete:
        return
    story_items = [
        item
        for item in repository.list_work_items()
        if item.canonical_story_issue_number == story_issue_number
        or story_issue_number in item.story_issue_numbers
    ]
    story_repo = next(
        (item.repo for item in story_items if item.repo is not None), None
    )
    if story_repo is None:
        return
    if hasattr(repository, "set_program_story_execution_status_with_propagation"):
        repository.set_program_story_execution_status_with_propagation(
            repo=story_repo,
            issue_number=story_issue_number,
            execution_status="done",
        )


def _integrate_story_branch(
    *,
    repository: StoryRepository,
    story_issue_number: int,
    story_work_items: list[WorkItem],
    story_complete: bool,
    story_integrator: StoryIntegratorAdapter | None,
) -> str | None:
    if not story_complete or story_integrator is None:
        return None
    integration_result = invoke_story_integrator(
        story_integrator,
        story_issue_number=story_issue_number,
        story_work_items=story_work_items,
    )
    story_repo = next(
        (item.repo for item in story_work_items if item.repo is not None), None
    )
    if story_repo is not None and hasattr(repository, "record_story_integration_run"):
        repository.record_story_integration_run(
            StoryIntegrationRun(
                repo=story_repo,
                story_issue_number=story_issue_number,
                merged=getattr(integration_result, "merged", False),
                promoted=getattr(integration_result, "promoted", False),
                merge_commit_sha=getattr(integration_result, "merge_commit_sha", None),
                promotion_commit_sha=getattr(
                    integration_result, "promotion_commit_sha", None
                ),
                blocked_reason=getattr(integration_result, "blocked_reason", None),
                summary=getattr(integration_result, "summary", ""),
            )
        )
    pull_number = getattr(integration_result, "pull_number", None)
    pull_url = getattr(integration_result, "pull_url", None)
    if (
        story_repo is not None
        and isinstance(pull_number, int)
        and isinstance(pull_url, str)
        and hasattr(repository, "record_story_pull_request_link")
    ):
        repository.record_story_pull_request_link(
            StoryPullRequestLink(
                repo=story_repo,
                story_issue_number=story_issue_number,
                pull_number=pull_number,
                pull_url=pull_url,
            )
        )
    return getattr(integration_result, "blocked_reason", None)
