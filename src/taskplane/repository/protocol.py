"""
ControlPlaneRepository Protocol definition.

This module defines the interface for repository implementations.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..models import (
    ApprovalEvent,
    EpicExecutionState,
    ExecutionRun,
    GuardrailViolation,
    OperatorRequest,
    ProgramStory,
    QueueEvaluation,
    StoryIntegrationRun,
    StoryPullRequestLink,
    StoryVerificationRun,
    TaskSpecDraft,
    VerificationEvidence,
    WorkClaim,
    WorkDependency,
    WorkItem,
    WorkStatus,
    WorkTarget,
)


class WorkStateRepository(Protocol):
    def list_work_items(self) -> list[WorkItem]: ...
    def list_active_work_items(self) -> list[WorkItem]: ...
    def list_dependencies(self) -> list[WorkDependency]: ...
    def list_targets_by_work_id(self) -> dict[str, list[WorkTarget]]: ...
    def sync_ready_states(self) -> None: ...
    def get_work_item(self, work_id: str) -> WorkItem: ...
    def update_work_status(
        self,
        work_id: str,
        status: WorkStatus,
        *,
        blocked_reason: str | None = None,
        decision_required: bool = False,
        attempt_count: int | None = None,
        last_failure_reason: str | None = None,
        next_eligible_at: str | None = None,
    ) -> None: ...
    def mark_blocked(
        self, work_id: str, violations: list[GuardrailViolation]
    ) -> None: ...


class ClaimRepository(Protocol):
    def list_work_claims(self) -> list[WorkClaim]: ...
    def list_active_work_claims(self) -> list[WorkClaim]: ...
    def upsert_work_claim(self, claim: WorkClaim) -> None: ...
    def delete_work_claim(self, work_id: str) -> None: ...
    def renew_work_claim(
        self, work_id: str, *, lease_token: str
    ) -> WorkClaim | None: ...
    def set_program_epic_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def set_program_epic_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def set_program_story_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...

    def list_dependencies(self) -> list[WorkDependency]: ...

    def list_targets_by_work_id(self) -> dict[str, list[WorkTarget]]: ...

    def sync_ready_states(self) -> None: ...

    def claim_ready_work_item(
        self,
        work_id: str,
        *,
        worker_name: str,
        workspace_path: str,
        branch_name: str,
        claimed_paths: tuple[str, ...],
    ) -> WorkItem | None: ...

    def claim_next_executable_work_item(
        self,
        *,
        worker_name: str,
        queue_evaluation: QueueEvaluation,
        candidate_work_items: list[WorkItem],
        workspace_path_by_work_id: dict[str, str] | None = None,
        branch_name_by_work_id: dict[str, str] | None = None,
    ) -> WorkItem | None: ...


class ExecutionRepository(Protocol):
    def record_run(self, run: ExecutionRun) -> int | None: ...
    def record_verification(self, evidence: VerificationEvidence) -> None: ...
    def record_commit_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        commit_sha: str,
        commit_message: str,
    ) -> None: ...

    def get_commit_link(self, work_id: str) -> dict[str, Any] | None: ...

    def record_pull_request_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        pull_number: int,
        pull_url: str,
    ) -> None: ...

    def get_pull_request_link(self, work_id: str) -> dict[str, Any] | None: ...

    def record_story_integration_run(self, run: StoryIntegrationRun) -> int | None: ...
    def record_story_verification_run(
        self, run: StoryVerificationRun
    ) -> int | None: ...
    def upsert_epic_execution_state(self, state: EpicExecutionState) -> None: ...
    def get_epic_execution_state(
        self, *, repo: str, epic_issue_number: int
    ) -> EpicExecutionState | None: ...
    def record_operator_request(self, request: OperatorRequest) -> int | None: ...
    def list_operator_requests(
        self,
        *,
        repo: str,
        epic_issue_number: int | None = None,
        include_closed: bool = False,
    ) -> list[OperatorRequest]: ...
    def close_operator_request(
        self,
        *,
        repo: str,
        epic_issue_number: int,
        reason_code: str,
        closed_reason: str,
    ) -> OperatorRequest | None: ...

    def record_story_pull_request_link(
        self, link: StoryPullRequestLink
    ) -> int | None: ...

    def get_story_pull_request_link(
        self, *, repo: str, story_issue_number: int
    ) -> dict[str, Any] | None: ...

    def record_task_spec_draft(self, draft: TaskSpecDraft) -> int | None: ...

    def record_approval_event(self, event: ApprovalEvent) -> int | None: ...

    def finalize_work_attempt(
        self,
        *,
        work_id: str,
        status: WorkStatus,
        execution_run: ExecutionRun,
        verification: VerificationEvidence | None = None,
        blocked_reason: str | None = None,
        decision_required: bool = False,
        attempt_count: int | None = None,
        last_failure_reason: str | None = None,
        next_eligible_at: str | None = None,
        commit_link: dict[str, Any] | None = None,
        pull_request_link: dict[str, Any] | None = None,
    ) -> None: ...
    def record_approval_event(self, event: ApprovalEvent) -> int | None: ...


class WorkerRepository(
    WorkStateRepository,
    ClaimRepository,
    ExecutionRepository,
    Protocol,
):
    """Minimal repository surface required by worker execution."""


class StoryRepository(WorkerRepository, Protocol):
    def list_story_work_item_ids(self, story_issue_number: int) -> list[str]: ...
    def list_program_stories_for_epic(
        self, *, repo: str, epic_issue_number: int
    ) -> list[ProgramStory]: ...
    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def set_program_story_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def record_story_integration_run(self, run: StoryIntegrationRun) -> int | None: ...
    def record_story_verification_run(
        self, run: StoryVerificationRun
    ) -> int | None: ...
    def record_story_pull_request_link(
        self, link: StoryPullRequestLink
    ) -> int | None: ...
    def get_story_pull_request_link(
        self, *, repo: str, story_issue_number: int
    ) -> dict[str, Any] | None: ...


class EpicRepository(Protocol):
    def list_program_stories_for_epic(
        self, *, repo: str, epic_issue_number: int
    ) -> list[ProgramStory]: ...
    def set_program_epic_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def set_program_epic_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...
    def upsert_epic_execution_state(self, state: EpicExecutionState) -> None: ...
    def get_epic_execution_state(
        self, *, repo: str, epic_issue_number: int
    ) -> EpicExecutionState | None: ...
    def record_operator_request(self, request: OperatorRequest) -> int | None: ...
    def list_operator_requests(
        self,
        *,
        repo: str,
        epic_issue_number: int | None = None,
        include_closed: bool = False,
    ) -> list[OperatorRequest]: ...
    def close_operator_request(
        self,
        *,
        repo: str,
        epic_issue_number: int,
        reason_code: str,
        closed_reason: str,
    ) -> OperatorRequest | None: ...


class StoryDecompositionRepository(Protocol):
    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...


class EpicDecompositionRepository(Protocol):
    def set_program_epic_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None: ...


class ControlPlaneRepository(
    StoryRepository,
    EpicRepository,
    StoryDecompositionRepository,
    EpicDecompositionRepository,
    Protocol,
):
    """Protocol defining the full repository interface for the control plane."""

    def record_task_spec_draft(self, draft: TaskSpecDraft) -> int | None: ...
