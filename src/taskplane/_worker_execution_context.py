from __future__ import annotations

from pathlib import Path

from .models import ExecutionContext, VerificationEvidence, WorkItem
from .protocols import VerifierAdapter, invoke_verifier
from .repository import WorkStateRepository


def _run_verifier_with_context(
    *,
    verifier: VerifierAdapter,
    work_item: WorkItem,
    workspace_path: Path | None,
    execution_context: ExecutionContext,
) -> VerificationEvidence:
    return invoke_verifier(
        verifier,
        work_item=work_item,
        workspace_path=workspace_path,
        execution_context=execution_context,
    )


def _build_execution_context(
    *,
    repository: WorkStateRepository,
    work_id: str,
    workspace_path: Path | None,
) -> ExecutionContext:
    work_item = repository.get_work_item(work_id)
    resolved_path = str(workspace_path) if workspace_path is not None else None
    session_policy = "fresh_session"
    resume_hint = None
    if work_item.last_failure_reason == "interrupted_retryable":
        session_policy = "resume_candidate"
        resume_hint = "interrupted_retryable"
    return ExecutionContext(
        work_id=work_item.id,
        title=work_item.title,
        lane=work_item.lane,
        wave=work_item.wave,
        repo=work_item.repo,
        source_issue_number=work_item.source_issue_number,
        canonical_story_issue_number=work_item.canonical_story_issue_number,
        story_issue_numbers=work_item.story_issue_numbers,
        planned_paths=work_item.planned_paths,
        workspace_path=resolved_path,
        project_dir=resolved_path,
        session_policy=session_policy,
        resume_hint=resume_hint,
        resume_context=None,
    )
