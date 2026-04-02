from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import (
    ExecutionGuardrailContext,
    StoryRunResult,
    VerificationEvidence,
    WorkItem,
)
from .story_runner import load_story_work_item_ids, run_story_until_settled
from .worker import ExecutionResult


def run_story_agent(
    *,
    story_issue_number: int,
    repository: Any,
    context: ExecutionGuardrailContext,
    worker_name: str,
    executor: Callable[[WorkItem], ExecutionResult],
    verifier: Callable[[WorkItem], VerificationEvidence],
    committer: object | None = None,
    story_github_writeback: object | None = None,
    story_integrator: object | None = None,
    workspace_manager: object | None = None,
    max_cycles: int = 100,
    story_loader: Callable[..., list[str]] = load_story_work_item_ids,
    story_runner: Callable[..., StoryRunResult] = run_story_until_settled,
    dsn: str | None = None,
) -> StoryRunResult:
    story_work_item_ids = story_loader(
        repository=repository,
        story_issue_number=story_issue_number,
    )
    return story_runner(
        story_issue_number=story_issue_number,
        story_work_item_ids=story_work_item_ids,
        repository=repository,
        context=context,
        worker_name=worker_name,
        executor=executor,
        verifier=verifier,
        committer=committer,
        story_github_writeback=story_github_writeback,
        story_integrator=story_integrator,
        workspace_manager=workspace_manager,
        max_cycles=max_cycles,
        dsn=dsn,
    )
