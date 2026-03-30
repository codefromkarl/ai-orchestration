"""
In-memory implementation of ControlPlaneRepository.

This module provides an in-memory repository for testing and development.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

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
    with_work_status,
)
from ..planner import derive_ready_work_ids
from ..queue import paths_conflict
from .helpers import _claim_has_path_conflict

LEASE_DURATION = timedelta(minutes=15)


@dataclass
class InMemoryControlPlaneRepository:
    """In-memory implementation of the ControlPlaneRepository protocol."""

    work_items: list[WorkItem]
    dependencies: list[WorkDependency]
    targets_by_work_id: dict[str, list[WorkTarget]]
    story_dependencies: list[tuple[int, int]] = field(default_factory=list)
    program_stories: list[ProgramStory] = field(default_factory=list)
    work_items_by_id: dict[str, WorkItem] = field(init=False)
    execution_runs: list[ExecutionRun] = field(default_factory=list)
    verification_evidence: list[VerificationEvidence] = field(default_factory=list)
    blocked_reasons: dict[str, list[GuardrailViolation]] = field(default_factory=dict)
    work_claims: list[WorkClaim] = field(default_factory=list)
    commit_links: dict[str, dict[str, Any]] = field(default_factory=dict)
    pull_request_links: dict[str, dict[str, Any]] = field(default_factory=dict)
    story_integration_runs: list[StoryIntegrationRun] = field(default_factory=list)
    story_verification_runs: list[StoryVerificationRun] = field(default_factory=list)
    epic_execution_states: dict[tuple[str, int], EpicExecutionState] = field(
        default_factory=dict
    )
    operator_requests: list[OperatorRequest] = field(default_factory=list)
    story_pull_request_links: dict[tuple[str, int], dict[str, Any]] = field(
        default_factory=dict
    )
    task_spec_drafts: list[TaskSpecDraft] = field(default_factory=list)
    approval_events: list[ApprovalEvent] = field(default_factory=list)
    _claim_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _allow_claim_on_successful_done_run: set[str] = field(
        default_factory=set, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.work_items_by_id = {item.id: item for item in self.work_items}

    def list_work_items(self) -> list[WorkItem]:
        return list(self.work_items_by_id.values())

    def list_active_work_items(self) -> list[WorkItem]:
        return self.list_work_items()

    def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
        return sorted(
            [
                item.id
                for item in self.work_items_by_id.values()
                if item.canonical_story_issue_number == story_issue_number
                or (
                    item.canonical_story_issue_number is None
                    and story_issue_number in item.story_issue_numbers
                )
            ]
        )

    def list_program_stories_for_epic(
        self, *, repo: str, epic_issue_number: int
    ) -> list[ProgramStory]:
        return sorted(
            [
                story
                for story in self.program_stories
                if story.repo == repo and story.epic_issue_number == epic_issue_number
            ],
            key=lambda story: story.issue_number,
        )

    def list_work_claims(self) -> list[WorkClaim]:
        return list(self.work_claims)

    def list_active_work_claims(self) -> list[WorkClaim]:
        active_claims: list[WorkClaim] = []
        now = datetime.now(UTC)
        for claim in self.work_claims:
            if claim.lease_expires_at is None:
                active_claims.append(claim)
                continue
            try:
                expires_at = datetime.fromisoformat(claim.lease_expires_at)
            except ValueError:
                active_claims.append(claim)
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at > now:
                active_claims.append(claim)
        return active_claims

    def upsert_work_claim(self, claim: WorkClaim) -> None:
        self.work_claims = [
            existing
            for existing in self.work_claims
            if existing.work_id != claim.work_id
        ]
        self.work_claims.append(claim)

    def delete_work_claim(self, work_id: str) -> None:
        self.work_claims = [
            existing for existing in self.work_claims if existing.work_id != work_id
        ]

    def renew_work_claim(self, work_id: str, *, lease_token: str) -> WorkClaim | None:
        with self._claim_lock:
            for index, claim in enumerate(self.work_claims):
                if claim.work_id != work_id:
                    continue
                active_claim = claim.lease_expires_at is None
                if not active_claim:
                    lease_expires_at = claim.lease_expires_at
                    if lease_expires_at is None:
                        active_claim = True
                        lease_expires_at = ""
                    try:
                        expires_at = datetime.fromisoformat(lease_expires_at)
                    except ValueError:
                        active_claim = True
                    else:
                        if expires_at.tzinfo is None:
                            expires_at = expires_at.replace(tzinfo=UTC)
                        active_claim = expires_at > datetime.now(UTC)
                if claim.lease_token != lease_token or not active_claim:
                    return None
                renewed = replace(
                    claim,
                    lease_expires_at=(datetime.now(UTC) + LEASE_DURATION).isoformat(),
                )
                self.work_claims[index] = renewed
                return renewed
        return None

    def set_program_epic_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        return None

    def set_program_epic_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        self.set_program_epic_execution_status(
            repo=repo,
            issue_number=issue_number,
            execution_status=execution_status,
        )

    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        return None

    def set_program_story_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        self.set_program_story_execution_status(
            repo=repo,
            issue_number=issue_number,
            execution_status=execution_status,
        )

    def list_dependencies(self) -> list[WorkDependency]:
        return list(self.dependencies)

    def list_targets_by_work_id(self) -> dict[str, list[WorkTarget]]:
        return {
            work_id: list(targets)
            for work_id, targets in self.targets_by_work_id.items()
        }

    def sync_ready_states(self) -> None:
        active_claim_ids = {claim.work_id for claim in self.list_active_work_claims()}
        for work_item in self.list_work_items():
            if (
                work_item.status == "in_progress"
                and work_item.id not in active_claim_ids
            ):
                self.update_work_status(work_item.id, "pending")
        ready_ids = derive_ready_work_ids(
            self.list_work_items(),
            self.dependencies,
            story_dependencies=self.story_dependencies,
        )
        for work_item in self.list_work_items():
            is_eligible = True
            if work_item.next_eligible_at is not None:
                try:
                    next_eligible_at = datetime.fromisoformat(
                        work_item.next_eligible_at
                    )
                except ValueError:
                    is_eligible = True
                else:
                    if next_eligible_at.tzinfo is None:
                        next_eligible_at = next_eligible_at.replace(tzinfo=UTC)
                    is_eligible = next_eligible_at <= datetime.now(UTC)
            if (
                work_item.status == "pending"
                and work_item.id in ready_ids
                and is_eligible
            ):
                self.update_work_status(work_item.id, "ready")
            elif work_item.status == "ready" and (
                work_item.id not in ready_ids or not is_eligible
            ):
                self.update_work_status(work_item.id, "pending")

    def claim_ready_work_item(
        self,
        work_id: str,
        *,
        worker_name: str,
        workspace_path: str,
        branch_name: str,
        claimed_paths: tuple[str, ...],
    ) -> WorkItem | None:
        with self._claim_lock:
            work_item = self.work_items_by_id.get(work_id)
            if work_item is None or work_item.status != "ready":
                return None
            if (
                self._has_successful_terminal_run(work_id)
                and work_id not in self._allow_claim_on_successful_done_run
            ):
                return None
            if _claim_has_path_conflict(
                claimed_paths, self.list_active_work_claims(), excluding_work_id=work_id
            ):
                return None
            claimed = with_work_status(work_item, "in_progress")
            self.work_items_by_id[work_id] = claimed
            self.upsert_work_claim(
                WorkClaim(
                    work_id=work_id,
                    worker_name=worker_name,
                    workspace_path=workspace_path,
                    branch_name=branch_name,
                    lease_token=secrets.token_hex(16),
                    lease_expires_at=(datetime.now(UTC) + LEASE_DURATION).isoformat(),
                    claimed_paths=claimed_paths,
                )
            )
            return claimed

    def claim_next_executable_work_item(
        self,
        *,
        worker_name: str,
        queue_evaluation: QueueEvaluation,
        candidate_work_items: list[WorkItem],
        workspace_path_by_work_id: dict[str, str] | None = None,
        branch_name_by_work_id: dict[str, str] | None = None,
    ) -> WorkItem | None:
        with self._claim_lock:
            work_items_by_id = {item.id: item for item in candidate_work_items}
            workspace_path_by_work_id = workspace_path_by_work_id or {}
            branch_name_by_work_id = branch_name_by_work_id or {}
            for work_id in queue_evaluation.executable_ids:
                work_item = self.work_items_by_id.get(work_id) or work_items_by_id.get(
                    work_id
                )
                if work_item is None:
                    continue
                self._allow_claim_on_successful_done_run.add(work_id)
                try:
                    claimed = self.claim_ready_work_item(
                        work_id,
                        worker_name=worker_name,
                        workspace_path=workspace_path_by_work_id.get(work_id, ""),
                        branch_name=branch_name_by_work_id.get(work_id, ""),
                        claimed_paths=work_item.planned_paths,
                    )
                finally:
                    self._allow_claim_on_successful_done_run.discard(work_id)
                if claimed is not None:
                    return claimed
            return None

    def get_work_item(self, work_id: str) -> WorkItem:
        return self.work_items_by_id[work_id]

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
    ) -> None:
        self.work_items_by_id[work_id] = replace(
            with_work_status(self.work_items_by_id[work_id], status),
            blocked_reason=blocked_reason if status == "blocked" else None,
            decision_required=decision_required if status == "blocked" else False,
            attempt_count=attempt_count
            if attempt_count is not None
            else self.work_items_by_id[work_id].attempt_count,
            last_failure_reason=last_failure_reason,
            next_eligible_at=next_eligible_at,
        )

    def record_run(self, run: ExecutionRun) -> int | None:
        self.execution_runs.append(run)
        return len(self.execution_runs)

    def record_verification(self, evidence: VerificationEvidence) -> None:
        self.verification_evidence.append(evidence)

    def record_commit_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        commit_sha: str,
        commit_message: str,
    ) -> None:
        if work_id in self.commit_links:
            raise ValueError("commit link already exists")
        self.commit_links[work_id] = {
            "work_id": work_id,
            "repo": repo,
            "issue_number": issue_number,
            "commit_sha": commit_sha,
            "commit_message": commit_message,
        }

    def get_commit_link(self, work_id: str) -> dict[str, Any] | None:
        return self.commit_links.get(work_id)

    def record_pull_request_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        pull_number: int,
        pull_url: str,
    ) -> None:
        if work_id in self.pull_request_links:
            raise ValueError("pull request link already exists")
        self.pull_request_links[work_id] = {
            "work_id": work_id,
            "repo": repo,
            "issue_number": issue_number,
            "pull_number": pull_number,
            "pull_url": pull_url,
        }

    def get_pull_request_link(self, work_id: str) -> dict[str, Any] | None:
        return self.pull_request_links.get(work_id)

    def record_story_integration_run(self, run: StoryIntegrationRun) -> int | None:
        self.story_integration_runs.append(run)
        return len(self.story_integration_runs)

    def record_story_verification_run(self, run: StoryVerificationRun) -> int | None:
        self.story_verification_runs.append(run)
        return len(self.story_verification_runs)

    def upsert_epic_execution_state(self, state: EpicExecutionState) -> None:
        self.epic_execution_states[(state.repo, state.epic_issue_number)] = state

    def get_epic_execution_state(
        self, *, repo: str, epic_issue_number: int
    ) -> EpicExecutionState | None:
        return self.epic_execution_states.get((repo, epic_issue_number))

    def record_operator_request(self, request: OperatorRequest) -> int | None:
        self.operator_requests.append(request)
        return len(self.operator_requests)

    def list_operator_requests(
        self,
        *,
        repo: str,
        epic_issue_number: int | None = None,
        include_closed: bool = False,
    ) -> list[OperatorRequest]:
        return [
            request
            for request in self.operator_requests
            if request.repo == repo
            and (
                epic_issue_number is None
                or request.epic_issue_number == epic_issue_number
            )
            and (include_closed or request.status != "closed")
        ]

    def close_operator_request(
        self,
        *,
        repo: str,
        epic_issue_number: int,
        reason_code: str,
        closed_reason: str,
    ) -> OperatorRequest | None:
        for index, request in enumerate(self.operator_requests):
            if (
                request.repo == repo
                and request.epic_issue_number == epic_issue_number
                and request.reason_code == reason_code
                and request.status == "open"
            ):
                closed_request = replace(
                    request,
                    status="closed",
                    closed_at=datetime.now(UTC),
                    closed_reason=closed_reason,
                )
                self.operator_requests[index] = closed_request
                epic_key = (repo, epic_issue_number)
                epic_state = self.epic_execution_states.get(epic_key)
                if epic_state is not None:
                    has_other_open_requests = any(
                        existing.repo == repo
                        and existing.epic_issue_number == epic_issue_number
                        and existing.status == "open"
                        for request_index, existing in enumerate(self.operator_requests)
                        if request_index != index
                    )
                    self.epic_execution_states[epic_key] = replace(
                        epic_state,
                        operator_attention_required=has_other_open_requests,
                        last_operator_action_at=closed_request.closed_at,
                        last_operator_action_reason=closed_reason,
                    )
                return closed_request
        return None

    def record_story_pull_request_link(self, link: StoryPullRequestLink) -> int | None:
        key = (link.repo, link.story_issue_number)
        self.story_pull_request_links[key] = {
            "repo": link.repo,
            "story_issue_number": link.story_issue_number,
            "pull_number": link.pull_number,
            "pull_url": link.pull_url,
        }
        return len(self.story_pull_request_links)

    def get_story_pull_request_link(
        self, *, repo: str, story_issue_number: int
    ) -> dict[str, Any] | None:
        return self.story_pull_request_links.get((repo, story_issue_number))

    def record_task_spec_draft(self, draft: TaskSpecDraft) -> int | None:
        self.task_spec_drafts.append(draft)
        return len(self.task_spec_drafts)

    def record_approval_event(self, event: ApprovalEvent) -> int | None:
        self.approval_events.append(event)
        return len(self.approval_events)

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
    ) -> None:
        effective_status = status
        effective_blocked_reason = blocked_reason
        effective_decision_required = decision_required
        if status == "blocked" and self._has_successful_terminal_run(work_id):
            effective_status = "done"
            effective_blocked_reason = None
            effective_decision_required = False
        self.update_work_status(
            work_id,
            effective_status,
            blocked_reason=effective_blocked_reason,
            decision_required=effective_decision_required,
            attempt_count=attempt_count,
            last_failure_reason=last_failure_reason,
            next_eligible_at=next_eligible_at,
        )
        run_id = self.record_run(execution_run)
        if verification is not None:
            self.record_verification(
                replace(verification, run_id=run_id or verification.run_id)
            )
        if commit_link is not None:
            self.record_commit_link(**commit_link)
        if pull_request_link is not None:
            self.record_pull_request_link(**pull_request_link)

    def _has_successful_terminal_run(self, work_id: str) -> bool:
        return any(
            run.work_id == work_id and run.status == "done"
            for run in self.execution_runs
        )

    def mark_blocked(self, work_id: str, violations: list[GuardrailViolation]) -> None:
        message = "\n".join(
            f"{violation.code}: {violation.target_path}" for violation in violations
        )
        self.update_work_status(
            work_id,
            "blocked",
            blocked_reason=message,
            decision_required=any(
                violation.code == "human-approval-required" for violation in violations
            ),
        )
        self.blocked_reasons[work_id] = violations
