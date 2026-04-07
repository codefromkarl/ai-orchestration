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
    BlockingMode,
    EpicExecutionState,
    ExecutionRun,
    GuardrailViolation,
    NaturalLanguageIntent,
    OperatorRequest,
    OrchestratorSession,
    ProgramStory,
    QueueEvaluation,
    StoryIntegrationRun,
    StoryPullRequestLink,
    StoryVerificationRun,
    TaskSpecDraft,
    TaskType,
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
INTAKE_EPIC_START = 1_500_000_000
INTAKE_STORY_START = 1_600_000_000


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
    natural_language_intents: dict[str, NaturalLanguageIntent] = field(
        default_factory=dict
    )
    orchestrator_sessions: dict[str, OrchestratorSession] = field(default_factory=dict)
    orchestrator_session_jobs: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
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

    def create_ad_hoc_work_item(
        self,
        *,
        work_id: str,
        repo: str,
        title: str,
        lane: str = "general",
        wave: str = "Direct",
        task_type: TaskType = "core_path",
        blocking_mode: BlockingMode = "soft",
        planned_paths: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> WorkItem:
        metadata = metadata or {}
        work_item = WorkItem(
            id=work_id,
            repo=repo,
            title=title,
            lane=lane,
            wave=wave,
            status="ready",
            task_type=task_type,
            blocking_mode=blocking_mode,
            planned_paths=planned_paths,
        )
        self.work_items_by_id[work_id] = work_item
        self.work_items.append(work_item)
        self.targets_by_work_id.setdefault(work_id, [])
        return work_item

    def list_story_work_item_ids(
        self, story_issue_number: int, repo: str | None = None
    ) -> list[str]:
        return sorted(
            [
                item.id
                for item in self.work_items_by_id.values()
                if (repo is None or item.repo is None or item.repo == repo)
                and (
                    item.canonical_story_issue_number == story_issue_number
                    or (
                        item.canonical_story_issue_number is None
                        and story_issue_number in item.story_issue_numbers
                    )
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
        self._repair_or_recover_ready_state_inputs()
        ready_ids = self._derive_ready_candidate_ids()
        self._apply_ready_state_transitions(ready_ids)

    def _repair_or_recover_ready_state_inputs(self) -> None:
        active_claim_ids = {claim.work_id for claim in self.list_active_work_claims()}
        for work_item in self.list_work_items():
            if (
                work_item.status == "in_progress"
                and work_item.id not in active_claim_ids
            ):
                self.update_work_status(work_item.id, "pending")

    def _derive_ready_candidate_ids(self) -> set[str]:
        return set(
            derive_ready_work_ids(
                self.list_work_items(),
                self.dependencies,
                story_dependencies=self.story_dependencies,
            )
        )

    def _apply_ready_state_transitions(self, ready_ids: set[str]) -> None:
        for work_item in self.list_work_items():
            is_eligible = self._is_ready_transition_eligible(work_item)
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

    def _is_ready_transition_eligible(self, work_item: WorkItem) -> bool:
        if work_item.next_eligible_at is None:
            return True
        try:
            next_eligible_at = datetime.fromisoformat(work_item.next_eligible_at)
        except ValueError:
            return True
        if next_eligible_at.tzinfo is None:
            next_eligible_at = next_eligible_at.replace(tzinfo=UTC)
        return next_eligible_at <= datetime.now(UTC)

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

    def record_natural_language_intent(
        self, intent: NaturalLanguageIntent
    ) -> str | None:
        self.natural_language_intents[intent.id] = intent
        return intent.id

    def update_natural_language_intent(self, intent: NaturalLanguageIntent) -> None:
        self.natural_language_intents[intent.id] = intent

    def get_natural_language_intent(
        self, intent_id: str
    ) -> NaturalLanguageIntent | None:
        return self.natural_language_intents.get(intent_id)

    def list_natural_language_intents(
        self, *, repo: str
    ) -> list[NaturalLanguageIntent]:
        return [
            intent
            for intent in self.natural_language_intents.values()
            if intent.repo == repo
        ]

    def promote_natural_language_proposal(
        self,
        *,
        intent_id: str,
        proposal: dict[str, Any],
        approver: str,
        promotion_mode: str | None = None,
    ) -> int:
        intent = self.natural_language_intents[intent_id]
        normalized_mode = (
            str(promotion_mode or proposal.get("promotion_mode") or "local")
            .strip()
            .lower()
        )
        epic_issue_number = INTAKE_EPIC_START + len(self.natural_language_intents)
        epic_payload = proposal.get("epic") if isinstance(proposal, dict) else {}
        if not isinstance(epic_payload, dict):
            epic_payload = {}
        stories_payload = proposal.get("stories") if isinstance(proposal, dict) else []
        if not isinstance(stories_payload, list):
            stories_payload = []

        story_key_to_issue_number: dict[str, int] = {}
        next_story_issue_number = INTAKE_STORY_START + len(self.program_stories)
        for index, story_payload in enumerate(stories_payload, start=1):
            if not isinstance(story_payload, dict):
                continue
            story_issue_number = next_story_issue_number
            next_story_issue_number += 1
            story_key = str(story_payload.get("story_key") or f"S{index}")
            story_key_to_issue_number[story_key] = story_issue_number
            self.program_stories.append(
                ProgramStory(
                    issue_number=story_issue_number,
                    repo=intent.repo,
                    epic_issue_number=epic_issue_number,
                    title=str(story_payload.get("title") or f"Story {index}"),
                    lane=str(
                        story_payload.get("lane")
                        or epic_payload.get("lane")
                        or "Lane 01"
                    ),
                    complexity=str(story_payload.get("complexity") or "medium"),
                    program_status="approved",
                    execution_status="active",
                    active_wave=f"wave-{index}",
                    notes=f"intake:{intent_id}",
                )
            )

        created_work_ids: list[str] = []
        work_dependencies: list[WorkDependency] = []
        for story_index, story_payload in enumerate(stories_payload, start=1):
            if not isinstance(story_payload, dict):
                continue
            story_issue_number = story_key_to_issue_number[
                str(story_payload.get("story_key") or f"S{story_index}")
            ]
            task_payloads = story_payload.get("tasks")
            if not isinstance(task_payloads, list):
                task_payloads = []
            story_work_ids: list[str] = []
            for task_index, task_payload in enumerate(task_payloads, start=1):
                if not isinstance(task_payload, dict):
                    continue
                work_id = f"intent-{intent_id}-t{story_index}-{task_index}"
                planned_paths_raw = task_payload.get("planned_paths")
                planned_paths = (
                    tuple(
                        str(path)
                        for path in planned_paths_raw
                        if isinstance(path, str) and path.strip()
                    )
                    if isinstance(planned_paths_raw, list)
                    else ()
                )
                work_item = WorkItem(
                    id=work_id,
                    repo=intent.repo,
                    title=str(
                        task_payload.get("title") or f"Task {story_index}.{task_index}"
                    ),
                    lane=str(
                        task_payload.get("lane")
                        or story_payload.get("lane")
                        or epic_payload.get("lane")
                        or "Lane 01"
                    ),
                    wave=str(task_payload.get("wave") or f"wave-{story_index}"),
                    status="pending",
                    task_type="core_path",
                    blocking_mode="hard",
                    canonical_story_issue_number=story_issue_number,
                    story_issue_numbers=(story_issue_number,),
                    source_issue_number=None
                    if normalized_mode == "local"
                    else story_issue_number,
                    planned_paths=planned_paths,
                )
                self.work_items_by_id[work_id] = work_item
                self.work_items.append(work_item)
                self.targets_by_work_id.setdefault(work_id, [])
                story_work_ids.append(work_id)
                created_work_ids.append(work_id)
                self.record_task_spec_draft(
                    TaskSpecDraft(
                        repo=intent.repo,
                        story_issue_number=story_issue_number,
                        title=work_item.title,
                        complexity=str(story_payload.get("complexity") or "medium"),
                        goal=str(task_payload.get("title") or work_item.title),
                        allowed_paths=planned_paths,
                        dod=tuple(
                            str(item)
                            for item in (task_payload.get("dod") or [])
                            if str(item).strip()
                        ),
                        verification=tuple(
                            str(item)
                            for item in (task_payload.get("verification") or [])
                            if str(item).strip()
                        ),
                        references=(intent.id,),
                    )
                )

            depends_on_story_keys = story_payload.get("depends_on_story_keys")
            if isinstance(depends_on_story_keys, list):
                for depends_on_story_key in depends_on_story_keys:
                    dependency_story_issue_number = story_key_to_issue_number.get(
                        str(depends_on_story_key)
                    )
                    if dependency_story_issue_number is None:
                        continue
                    self.story_dependencies.append(
                        (story_issue_number, dependency_story_issue_number)
                    )
                    dependency_work_ids = [
                        work_id
                        for work_id in created_work_ids
                        if self.work_items_by_id[work_id].canonical_story_issue_number
                        == dependency_story_issue_number
                    ]
                    for story_work_id in story_work_ids:
                        for dependency_work_id in dependency_work_ids:
                            work_dependencies.append(
                                WorkDependency(
                                    work_id=story_work_id,
                                    depends_on_work_id=dependency_work_id,
                                )
                            )

        for dependency in work_dependencies:
            if dependency not in self.dependencies:
                self.dependencies.append(dependency)

        self.sync_ready_states()
        updated_intent = replace(
            intent,
            status="promoted",
            promoted_epic_issue_number=epic_issue_number,
            approved_by=approver,
            approved_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.natural_language_intents[intent_id] = updated_intent
        return epic_issue_number

    def record_approval_event(self, event: ApprovalEvent) -> int | None:
        self.approval_events.append(event)
        return len(self.approval_events)

    def create_orchestrator_session(
        self,
        *,
        repo: str,
        host_tool: str,
        started_by: str,
        watch_scope_json: dict[str, Any] | None = None,
        current_phase: str = "observe",
        objective_summary: str | None = None,
        plan_summary: str | None = None,
        handoff_summary: str | None = None,
    ) -> OrchestratorSession:
        session = OrchestratorSession(
            id=f"orch-{secrets.token_hex(6)}",
            repo=repo,
            host_tool=host_tool,
            started_by=started_by,
            watch_scope_json=watch_scope_json or {},
            current_phase=current_phase,
            objective_summary=objective_summary,
            plan_summary=plan_summary,
            handoff_summary=handoff_summary,
        )
        self.orchestrator_sessions[session.id] = session
        self.orchestrator_session_jobs.setdefault(session.id, [])
        return session

    def get_orchestrator_session(self, session_id: str) -> OrchestratorSession | None:
        return self.orchestrator_sessions.get(session_id)

    def update_orchestrator_session_scope(
        self, *, session_id: str, watch_scope_json: dict[str, Any]
    ) -> OrchestratorSession:
        session = self.orchestrator_sessions[session_id]
        updated = replace(session, watch_scope_json=watch_scope_json)
        self.orchestrator_sessions[session_id] = updated
        return updated

    def set_orchestrator_session_status(
        self, *, session_id: str, status: str
    ) -> OrchestratorSession:
        session = self.orchestrator_sessions[session_id]
        updated = replace(session, status=status)
        self.orchestrator_sessions[session_id] = updated
        return updated

    def record_orchestrator_session_job(
        self, *, session_id: str, job: dict[str, Any]
    ) -> None:
        self.orchestrator_session_jobs.setdefault(session_id, []).append(dict(job))

    def list_orchestrator_session_jobs(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(job) for job in self.orchestrator_session_jobs.get(session_id, [])]

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
        self._apply_finalization_status_update(
            work_id=work_id,
            status=status,
            blocked_reason=blocked_reason,
            decision_required=decision_required,
            attempt_count=attempt_count,
            last_failure_reason=last_failure_reason,
            next_eligible_at=next_eligible_at,
        )
        self._record_finalization_followups(
            execution_run=execution_run,
            verification=verification,
            commit_link=commit_link,
            pull_request_link=pull_request_link,
        )

    def _apply_finalization_status_update(
        self,
        *,
        work_id: str,
        status: WorkStatus,
        blocked_reason: str | None = None,
        decision_required: bool = False,
        attempt_count: int | None = None,
        last_failure_reason: str | None = None,
        next_eligible_at: str | None = None,
    ) -> None:
        self.update_work_status(
            work_id,
            status,
            blocked_reason=blocked_reason,
            decision_required=decision_required,
            attempt_count=attempt_count,
            last_failure_reason=last_failure_reason,
            next_eligible_at=next_eligible_at,
        )

    def _record_finalization_followups(
        self,
        *,
        execution_run: ExecutionRun,
        verification: VerificationEvidence | None = None,
        commit_link: dict[str, Any] | None = None,
        pull_request_link: dict[str, Any] | None = None,
    ) -> None:
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
