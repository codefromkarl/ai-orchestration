from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .models import VerificationEvidence, WorkItem


class ExecutorAdapter(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class VerifierAdapter(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> VerificationEvidence: ...


class TaskWritebackAdapter(Protocol):
    def __call__(
        self,
        *,
        repo: str,
        issue_number: int,
        status: str,
        decision_required: bool = False,
    ) -> None: ...


class StoryWritebackAdapter(Protocol):
    def __call__(
        self,
        *,
        repo: str,
        issue_number: int,
        status: str,
        decision_required: bool = False,
    ) -> None: ...


class StoryIntegratorAdapter(Protocol):
    def __call__(
        self,
        *,
        story_issue_number: int,
        story_work_items: list[WorkItem],
    ) -> Any: ...


class WorkspaceAdapter(Protocol):
    repo_root: Path
    worktree_root: Path

    def prepare(
        self, *, work_item: WorkItem, worker_name: str, repository: Any
    ) -> Path: ...

    def release(self, *, work_item: WorkItem, repository: Any) -> None: ...


class IntakeAdapter(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class HierarchyRunnerAdapter(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
