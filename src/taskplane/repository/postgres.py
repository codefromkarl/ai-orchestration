"""
PostgreSQL implementation of ControlPlaneRepository.

This module provides the main production repository implementation using PostgreSQL.
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ..models import (
    ApprovalEvent,
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
    VerificationEvidence,
    WorkClaim,
    WorkDependency,
    WorkItem,
    WorkStatus,
    WorkTarget,
)
from ._postgres_execution import (
    apply_finalization_status_update,
    record_finalization_followups,
)
from ._postgres_claims import (
    CLAIM_READY_WORK_ITEM_SQL,
    build_claim_ready_work_item_params,
)
from ._postgres_governance import (
    SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL,
    SET_PROGRAM_EPIC_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
    SET_PROGRAM_STORY_EXECUTION_STATUS_SQL,
    SET_PROGRAM_STORY_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
    build_epic_status_with_propagation_params,
    build_story_status_with_propagation_params,
)
from ._postgres_intake import (
    RECORD_NATURAL_LANGUAGE_INTENT_SQL,
    build_get_natural_language_intent_query,
    build_list_natural_language_intents_query,
    build_record_natural_language_intent_params,
)
from ._postgres_operator_requests import (
    CLOSE_OPERATOR_REQUEST_SQL,
    RECORD_OPERATOR_REQUEST_SQL,
    build_list_operator_requests_query,
    build_record_operator_request_params,
)
from ._postgres_promotion import promote_intent_proposal_via_cursor
from ._postgres_row_mapping import (
    row_to_natural_language_intent,
    row_to_operator_request,
    row_to_program_story,
    row_to_work_claim,
    row_to_work_item,
    value,
    value_optional,
)

LEASE_DURATION = timedelta(minutes=15)
INTAKE_EPIC_START = 1_500_000_000
INTAKE_STORY_START = 1_600_000_000


def _orchestrator_session_status(value: Any) -> str:
    raw = str(value or "active")
    return raw if raw in {"active", "paused", "closed"} else "active"


def _orchestrator_session_phase(value: Any) -> str:
    raw = str(value or "observe")
    allowed = {
        "observe",
        "plan",
        "act",
        "verify",
        "decide_next",
        "escalate",
        "suspend",
    }
    return raw if raw in allowed else "observe"


class PostgresControlPlaneRepository:
    """PostgreSQL implementation of the ControlPlaneRepository protocol."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def list_work_items(self) -> list[WorkItem]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repo, title, lane, wave, status, complexity, attempt_count, last_failure_reason, next_eligible_at, source_issue_number, dod_json,
                       canonical_story_issue_number, task_type, blocking_mode,
                       blocked_reason, decision_required
                FROM work_item
                ORDER BY id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_work_item(row) for row in rows]

    def list_active_work_items(self) -> list[WorkItem]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repo, title, lane, wave, status, complexity, attempt_count, last_failure_reason, next_eligible_at, source_issue_number, dod_json,
                       canonical_story_issue_number, task_type, blocking_mode,
                       blocked_reason, decision_required
                FROM v_active_task_queue
                ORDER BY id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_work_item(row) for row in rows]

    def create_ad_hoc_work_item(
        self,
        *,
        work_id: str,
        repo: str,
        title: str,
        lane: str = "general",
        wave: str = "Direct",
        task_type: str = "core_path",
        blocking_mode: str = "soft",
        planned_paths: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> WorkItem:
        dod_payload = {
            "story_issue_numbers": [],
            "related_story_issue_numbers": [],
            "planned_paths": list(planned_paths),
        }
        if metadata:
            dod_payload.update(metadata)

        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id,
                    repo,
                    title,
                    lane,
                    wave,
                    status,
                    task_type,
                    blocking_mode,
                    dod_json
                )
                VALUES (%s, %s, %s, %s, %s, 'ready', %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    repo = EXCLUDED.repo,
                    title = EXCLUDED.title,
                    lane = EXCLUDED.lane,
                    wave = EXCLUDED.wave,
                    status = 'ready',
                    task_type = EXCLUDED.task_type,
                    blocking_mode = EXCLUDED.blocking_mode,
                    dod_json = EXCLUDED.dod_json,
                    blocked_reason = NULL,
                    decision_required = FALSE,
                    updated_at = NOW()
                RETURNING id, repo, title, lane, wave, status, complexity,
                          attempt_count, last_failure_reason, next_eligible_at,
                          source_issue_number, dod_json, canonical_story_issue_number,
                          task_type, blocking_mode, blocked_reason, decision_required
                """,
                (
                    work_id,
                    repo,
                    title,
                    lane,
                    wave,
                    task_type,
                    blocking_mode,
                    json.dumps(dod_payload, ensure_ascii=False),
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            raise RuntimeError(f"failed to create ad hoc work item: {work_id}")
        return self._row_to_work_item(row)

    def list_work_claims(self) -> list[WorkClaim]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                FROM work_claim
                ORDER BY claimed_at, work_id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_work_claim(row) for row in rows]

    def list_active_work_claims(self) -> list[WorkClaim]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                FROM work_claim
                WHERE lease_expires_at IS NULL OR lease_expires_at > NOW()
                ORDER BY claimed_at, work_id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_work_claim(row) for row in rows]

    def upsert_work_claim(self, claim: WorkClaim) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id,
                    worker_name,
                    workspace_path,
                    branch_name,
                    lease_token,
                    lease_expires_at,
                    claimed_paths
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (work_id) DO UPDATE SET
                    worker_name = EXCLUDED.worker_name,
                    workspace_path = EXCLUDED.workspace_path,
                    branch_name = EXCLUDED.branch_name,
                    lease_token = EXCLUDED.lease_token,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    claimed_paths = EXCLUDED.claimed_paths,
                    claimed_at = NOW()
                """,
                (
                    claim.work_id,
                    claim.worker_name,
                    claim.workspace_path,
                    claim.branch_name,
                    claim.lease_token,
                    claim.lease_expires_at,
                    json.dumps(list(claim.claimed_paths)),
                ),
            )
        self._connection.commit()

    def delete_work_claim(self, work_id: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM work_claim
                WHERE work_id = %s
                """,
                (work_id,),
            )
        self._connection.commit()

    def renew_work_claim(self, work_id: str, *, lease_token: str) -> WorkClaim | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE work_claim
                SET lease_expires_at = %s,
                    claimed_at = NOW()
                WHERE work_id = %s
                  AND lease_token = %s
                  AND (lease_expires_at IS NULL OR lease_expires_at > NOW())
                RETURNING work_id, worker_name, workspace_path, branch_name, lease_token, lease_expires_at, claimed_paths
                """,
                (
                    (datetime.now(UTC) + LEASE_DURATION).isoformat(),
                    work_id,
                    lease_token,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        return self._row_to_work_claim(row)

    def set_program_epic_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL,
                (execution_status, repo, issue_number),
            )
        self._connection.commit()

    def set_program_epic_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL,
                (execution_status, repo, issue_number),
            )
            cursor.execute(
                SET_PROGRAM_EPIC_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
                build_epic_status_with_propagation_params(
                    repo=repo,
                    issue_number=issue_number,
                    execution_status=execution_status,
                ),
            )
        self._connection.commit()

    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                SET_PROGRAM_STORY_EXECUTION_STATUS_SQL,
                (execution_status, repo, issue_number),
            )
        self._connection.commit()

    def set_program_story_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                SET_PROGRAM_STORY_EXECUTION_STATUS_SQL,
                (execution_status, repo, issue_number),
            )
            cursor.execute(
                SET_PROGRAM_STORY_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
                build_story_status_with_propagation_params(
                    repo=repo,
                    issue_number=issue_number,
                    execution_status=execution_status,
                ),
            )
        self._connection.commit()

    def list_dependencies(self) -> list[WorkDependency]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, depends_on_work_id
                FROM work_dependency
                ORDER BY work_id, depends_on_work_id
                """
            )
            rows = cursor.fetchall()
        return [
            WorkDependency(
                work_id=self._value(row, "work_id"),
                depends_on_work_id=self._value(row, "depends_on_work_id"),
            )
            for row in rows
        ]

    def list_targets_by_work_id(self) -> dict[str, list[WorkTarget]]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, target_path, target_type, owner_lane, is_frozen, requires_human_approval
                FROM work_target
                ORDER BY work_id, id
                """
            )
            rows = cursor.fetchall()

        targets_by_work_id: dict[str, list[WorkTarget]] = {}
        for row in rows:
            target = WorkTarget(
                work_id=self._value(row, "work_id"),
                target_path=self._value(row, "target_path"),
                target_type=self._value(row, "target_type"),
                owner_lane=self._value(row, "owner_lane"),
                is_frozen=bool(self._value(row, "is_frozen")),
                requires_human_approval=bool(
                    self._value(row, "requires_human_approval")
                ),
            )
            targets_by_work_id.setdefault(target.work_id, []).append(target)
        return targets_by_work_id

    def sync_ready_states(self) -> None:
        with self._connection.cursor() as cursor:
            self._repair_or_recover_ready_state_inputs(cursor)
            ready_ids = self._derive_ready_candidate_ids(cursor)
            self._apply_ready_state_transitions(cursor, ready_ids)
        self._connection.commit()

    def _repair_or_recover_ready_state_inputs(self, cursor: Any) -> None:
        cursor.execute(
            """
            UPDATE work_item wi
            SET status = 'pending'::work_status,
                updated_at = NOW()
            WHERE wi.status = 'in_progress'
              AND NOT EXISTS (
                  SELECT 1
                  FROM work_claim wc
                  WHERE wc.work_id = wi.id
                    AND (wc.lease_expires_at IS NULL OR wc.lease_expires_at > NOW())
              )
            """
        )
        cursor.execute(
            """
            UPDATE work_item wi
            SET repo = ps.repo,
                updated_at = NOW()
            FROM program_story ps
            WHERE wi.canonical_story_issue_number = ps.issue_number
              AND wi.repo IS NULL
              AND ps.repo IS NOT NULL
            """
        )
        cursor.execute(
            """
            UPDATE work_item wi
            SET wave = COALESCE(pe.active_wave, ps.active_wave, 'Wave0'),
                updated_at = NOW()
            FROM program_story ps
            JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number
                                 AND pe.repo = ps.repo
            WHERE wi.canonical_story_issue_number = ps.issue_number
              AND wi.repo = ps.repo
              AND (wi.wave IS NULL OR wi.wave = 'unassigned')
            """
        )
        cursor.execute(
            """
            UPDATE work_item wi
            SET status = 'blocked'::work_status,
                blocked_reason = 'data_integrity_issue: ' ||
                    CASE
                        WHEN wi.repo IS NULL AND wi.canonical_story_issue_number IS NOT NULL
                            THEN 'missing_repo'
                        WHEN wi.wave IS NULL THEN 'missing_wave'
                        ELSE 'unknown'
                    END,
                updated_at = NOW()
            WHERE wi.status IN ('pending', 'ready')
              AND (
                  (wi.repo IS NULL AND wi.canonical_story_issue_number IS NOT NULL)
                  OR wi.wave IS NULL
              )
            """
        )

    def _derive_ready_candidate_ids(self, cursor: Any) -> set[str]:
        cursor.execute(
            """
            SELECT wi.id
            FROM work_item wi
            WHERE wi.status IN ('pending', 'ready')
              AND wi.repo IS NOT NULL
              AND wi.wave IS NOT NULL
              AND (wi.next_eligible_at IS NULL OR wi.next_eligible_at <= NOW())
              AND (
                    wi.canonical_story_issue_number IS NULL
                    OR EXISTS (
                        SELECT 1
                        FROM program_story current_story
                        WHERE current_story.repo = wi.repo
                          AND current_story.issue_number = wi.canonical_story_issue_number
                          AND current_story.execution_status IN ('active', 'done')
                    )
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM work_dependency wd
                    JOIN work_item dep ON dep.id = wd.depends_on_work_id
                    WHERE wd.work_id = wi.id
                      AND dep.status <> 'done'
                      AND dep.blocking_mode = 'hard'
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM story_dependency sd
                    JOIN program_story dep_story
                      ON dep_story.repo = wi.repo
                     AND dep_story.issue_number = sd.depends_on_story_issue_number
                    WHERE wi.canonical_story_issue_number = sd.story_issue_number
                      AND dep_story.execution_status <> 'done'
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM execution_session es
                    WHERE es.work_id = wi.id
                      AND es.status IN ('suspended', 'waiting_internal', 'waiting_external')
              )
            """
        )
        rows = cursor.fetchall()
        return {
            str(self._value(row, "id"))
            for row in rows
            if self._value(row, "id") is not None
        }

    def _apply_ready_state_transitions(self, cursor: Any, ready_ids: set[str]) -> None:
        ready_id_list = sorted(ready_ids)
        cursor.execute(
            """
            UPDATE work_item wi
            SET status = CASE
                    WHEN wi.id = ANY(%s::text[]) THEN 'ready'::work_status
                    ELSE 'pending'::work_status
                END,
                updated_at = NOW()
            WHERE wi.status IN ('pending', 'ready')
              AND wi.repo IS NOT NULL
              AND wi.wave IS NOT NULL
              AND (
                    (wi.status = 'pending' AND wi.id = ANY(%s::text[]))
                    OR (wi.status = 'ready' AND NOT (wi.id = ANY(%s::text[])))
              )
            """,
            (ready_id_list, ready_id_list, ready_id_list),
        )

    def claim_ready_work_item(
        self,
        work_id: str,
        *,
        worker_name: str,
        workspace_path: str,
        branch_name: str,
        claimed_paths: tuple[str, ...],
    ) -> WorkItem | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            safe_worker = re.sub(r"[^A-Za-z0-9_.:-]", "_", worker_name)
            safe_work_id = re.sub(r"[^A-Za-z0-9_.:-]", "_", work_id)
            cursor.execute(
                f"SET LOCAL application_name = 'claim_ready_work_item:{safe_worker}:{safe_work_id}'"
            )
            cursor.execute(
                CLAIM_READY_WORK_ITEM_SQL,
                build_claim_ready_work_item_params(
                    work_id=work_id,
                    worker_name=worker_name,
                    workspace_path=workspace_path,
                    branch_name=branch_name,
                    claimed_paths=claimed_paths,
                    lease_token=secrets.token_hex(16),
                    lease_expires_at=(datetime.now(UTC) + LEASE_DURATION).isoformat(),
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        return self._row_to_work_item(row)

    def claim_next_executable_work_item(
        self,
        *,
        worker_name: str,
        queue_evaluation: QueueEvaluation,
        candidate_work_items: list[WorkItem],
        workspace_path_by_work_id: dict[str, str] | None = None,
        branch_name_by_work_id: dict[str, str] | None = None,
    ) -> WorkItem | None:
        work_items_by_id = {item.id: item for item in candidate_work_items}
        workspace_path_by_work_id = workspace_path_by_work_id or {}
        branch_name_by_work_id = branch_name_by_work_id or {}
        for work_id in queue_evaluation.executable_ids:
            work_item = work_items_by_id.get(work_id)
            if work_item is None:
                continue
            if work_item.status not in {
                "ready",
                "pending",
            } and self._has_successful_terminal_run(work_id):
                continue
            claimed = self.claim_ready_work_item(
                work_id,
                worker_name=worker_name,
                workspace_path=workspace_path_by_work_id.get(work_id, ""),
                branch_name=branch_name_by_work_id.get(work_id, ""),
                claimed_paths=work_item.planned_paths,
            )
            if claimed is not None:
                return claimed
        return None

    def get_work_item(self, work_id: str) -> WorkItem:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repo, title, lane, wave, status, complexity, attempt_count, last_failure_reason, next_eligible_at, source_issue_number, dod_json,
                       canonical_story_issue_number, task_type, blocking_mode,
                       blocked_reason, decision_required
                FROM work_item
                WHERE id = %s
                """,
                (work_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise KeyError(work_id)
        return self._row_to_work_item(row)

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
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE work_item
                SET status = %s,
                    attempt_count = %s,
                    last_failure_reason = %s,
                    next_eligible_at = %s,
                    blocked_reason = %s,
                    decision_required = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    status,
                    attempt_count if attempt_count is not None else 0,
                    last_failure_reason,
                    next_eligible_at,
                    blocked_reason if status == "blocked" else None,
                    decision_required if status == "blocked" else False,
                    work_id,
                ),
            )
        self._connection.commit()

    def record_run(self, run: ExecutionRun) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_run (
                    work_id,
                    worker_name,
                    status,
                    branch_name,
                    command_digest,
                    summary,
                    exit_code,
                    elapsed_ms,
                    stdout_digest,
                    stderr_digest,
                    result_payload_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    run.work_id,
                    run.worker_name,
                    run.status,
                    getattr(run, "branch_name", None),
                    run.command_digest,
                    run.summary,
                    run.exit_code,
                    run.elapsed_ms,
                    run.stdout_digest,
                    run.stderr_digest,
                    json.dumps(run.result_payload_json)
                    if run.result_payload_json is not None
                    else None,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        return int(self._value(row, "id"))

    def list_story_work_item_ids(
        self, story_issue_number: int, repo: str | None = None
    ) -> list[str]:
        with self._connection.cursor() as cursor:
            if repo is None:
                cursor.execute(
                    """
                    SELECT id
                    FROM work_item
                    WHERE canonical_story_issue_number = %s
                       OR (
                            canonical_story_issue_number IS NULL
                        AND COALESCE(dod_json->'story_issue_numbers', '[]'::jsonb) @> %s::jsonb
                       )
                    ORDER BY source_issue_number, id
                    """,
                    (story_issue_number, json.dumps([story_issue_number])),
                )
            else:
                cursor.execute(
                    """
                    SELECT id
                    FROM work_item
                    WHERE repo = %s
                      AND (
                            canonical_story_issue_number = %s
                         OR (
                                canonical_story_issue_number IS NULL
                            AND COALESCE(dod_json->'story_issue_numbers', '[]'::jsonb) @> %s::jsonb
                         )
                      )
                    ORDER BY source_issue_number, id
                    """,
                    (repo, story_issue_number, json.dumps([story_issue_number])),
                )
            rows = cursor.fetchall()
        return [self._value(row, "id") for row in rows]

    def list_program_stories_for_epic(
        self, *, repo: str, epic_issue_number: int
    ) -> list[ProgramStory]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT issue_number, repo, epic_issue_number, title, lane, complexity,
                       program_status, execution_status, active_wave, notes
                FROM program_story
                WHERE repo = %s
                  AND epic_issue_number = %s
                ORDER BY issue_number
                """,
                (repo, epic_issue_number),
            )
            rows = cursor.fetchall()
        return [self._row_to_program_story(row) for row in rows]

    def record_verification(self, evidence: VerificationEvidence) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO verification_evidence (
                    run_id,
                    work_id,
                    check_type,
                    command,
                    passed,
                    output_digest,
                    exit_code,
                    elapsed_ms,
                    stdout_digest,
                    stderr_digest
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    evidence.run_id,
                    evidence.work_id,
                    evidence.check_type,
                    evidence.command,
                    evidence.passed,
                    evidence.output_digest,
                    evidence.exit_code,
                    evidence.elapsed_ms,
                    evidence.stdout_digest,
                    evidence.stderr_digest,
                ),
            )
        self._connection.commit()

    def record_commit_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        commit_sha: str,
        commit_message: str,
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_commit_link (
                    work_id,
                    repo,
                    issue_number,
                    commit_sha,
                    commit_message
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (work_id, repo, issue_number, commit_sha, commit_message),
            )
        self._connection.commit()

    def get_commit_link(self, work_id: str) -> dict[str, Any] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, repo, issue_number, commit_sha, commit_message
                FROM work_commit_link
                WHERE work_id = %s
                """,
                (work_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "work_id": self._value(row, "work_id"),
            "repo": self._value(row, "repo"),
            "issue_number": self._value(row, "issue_number"),
            "commit_sha": self._value(row, "commit_sha"),
            "commit_message": self._value(row, "commit_message"),
        }

    def record_pull_request_link(
        self,
        *,
        work_id: str,
        repo: str,
        issue_number: int,
        pull_number: int,
        pull_url: str,
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO pull_request_link (
                    work_id,
                    repo,
                    issue_number,
                    pull_number,
                    pull_url
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (work_id, repo, issue_number, pull_number, pull_url),
            )
        self._connection.commit()

    def get_pull_request_link(self, work_id: str) -> dict[str, Any] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_id, repo, issue_number, pull_number, pull_url
                FROM pull_request_link
                WHERE work_id = %s
                """,
                (work_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "work_id": self._value(row, "work_id"),
            "repo": self._value(row, "repo"),
            "issue_number": self._value(row, "issue_number"),
            "pull_number": self._value(row, "pull_number"),
            "pull_url": self._value(row, "pull_url"),
        }

    def record_story_integration_run(self, run: StoryIntegrationRun) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO story_integration_run (
                    repo,
                    story_issue_number,
                    merged,
                    promoted,
                    merge_commit_sha,
                    promotion_commit_sha,
                    blocked_reason,
                    summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run.repo,
                    run.story_issue_number,
                    run.merged,
                    run.promoted,
                    run.merge_commit_sha,
                    run.promotion_commit_sha,
                    run.blocked_reason,
                    run.summary,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

    def record_story_verification_run(self, run: StoryVerificationRun) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO story_verification_run (
                    repo,
                    story_issue_number,
                    check_type,
                    command,
                    passed,
                    summary,
                    output_digest,
                    exit_code,
                    elapsed_ms,
                    stdout_digest,
                    stderr_digest
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run.repo,
                    run.story_issue_number,
                    run.check_type,
                    run.command,
                    run.passed,
                    run.summary,
                    run.output_digest,
                    run.exit_code,
                    run.elapsed_ms,
                    run.stdout_digest,
                    run.stderr_digest,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

    def upsert_epic_execution_state(self, state: EpicExecutionState) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO epic_execution_state (
                    repo,
                    epic_issue_number,
                    status,
                    completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json,
                    blocked_reason_code,
                    operator_attention_required,
                    last_operator_action_at,
                    last_operator_action_reason,
                    last_progress_at,
                    stalled_since,
                    verification_status,
                    verification_reason_code,
                    last_verification_at,
                    verification_summary,
                    updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (repo, epic_issue_number) DO UPDATE SET
                    status = EXCLUDED.status,
                    completed_story_issue_numbers_json = EXCLUDED.completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json = EXCLUDED.blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json = EXCLUDED.remaining_story_issue_numbers_json,
                    blocked_reason_code = EXCLUDED.blocked_reason_code,
                    operator_attention_required = EXCLUDED.operator_attention_required,
                    last_operator_action_at = EXCLUDED.last_operator_action_at,
                    last_operator_action_reason = EXCLUDED.last_operator_action_reason,
                    last_progress_at = EXCLUDED.last_progress_at,
                    stalled_since = EXCLUDED.stalled_since,
                    verification_status = EXCLUDED.verification_status,
                    verification_reason_code = EXCLUDED.verification_reason_code,
                    last_verification_at = EXCLUDED.last_verification_at,
                    verification_summary = EXCLUDED.verification_summary,
                    updated_at = NOW()
                """,
                (
                    state.repo,
                    state.epic_issue_number,
                    state.status,
                    json.dumps(list(state.completed_story_issue_numbers)),
                    json.dumps(list(state.blocked_story_issue_numbers)),
                    json.dumps(list(state.remaining_story_issue_numbers)),
                    state.blocked_reason_code,
                    state.operator_attention_required,
                    state.last_operator_action_at,
                    state.last_operator_action_reason,
                    state.last_progress_at,
                    state.stalled_since,
                    state.verification_status,
                    state.verification_reason_code,
                    state.last_verification_at,
                    state.verification_summary,
                ),
            )
        self._connection.commit()

    def get_epic_execution_state(
        self, *, repo: str, epic_issue_number: int
    ) -> EpicExecutionState | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT repo,
                       epic_issue_number,
                       status,
                       completed_story_issue_numbers_json,
                       blocked_story_issue_numbers_json,
                       remaining_story_issue_numbers_json,
                       blocked_reason_code,
                       operator_attention_required,
                       last_operator_action_at,
                       last_operator_action_reason,
                       last_progress_at,
                       stalled_since,
                       verification_status,
                       verification_reason_code,
                       last_verification_at,
                       verification_summary
                FROM epic_execution_state
                WHERE repo = %s
                  AND epic_issue_number = %s
                """,
                (repo, epic_issue_number),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return EpicExecutionState(
            repo=self._value(row, "repo"),
            epic_issue_number=int(self._value(row, "epic_issue_number")),
            status=self._value(row, "status"),
            completed_story_issue_numbers=tuple(
                int(value)
                for value in (
                    self._value_optional(row, "completed_story_issue_numbers_json")
                    or []
                )
            ),
            blocked_story_issue_numbers=tuple(
                int(value)
                for value in (
                    self._value_optional(row, "blocked_story_issue_numbers_json") or []
                )
            ),
            remaining_story_issue_numbers=tuple(
                int(value)
                for value in (
                    self._value_optional(row, "remaining_story_issue_numbers_json")
                    or []
                )
            ),
            blocked_reason_code=self._value_optional(row, "blocked_reason_code"),
            operator_attention_required=bool(
                self._value_optional(row, "operator_attention_required") or False
            ),
            last_operator_action_at=self._value_optional(
                row, "last_operator_action_at"
            ),
            last_operator_action_reason=self._value_optional(
                row, "last_operator_action_reason"
            ),
            last_progress_at=self._value_optional(row, "last_progress_at"),
            stalled_since=self._value_optional(row, "stalled_since"),
            verification_status=self._value_optional(row, "verification_status"),
            verification_reason_code=self._value_optional(
                row, "verification_reason_code"
            ),
            last_verification_at=self._value_optional(row, "last_verification_at"),
            verification_summary=self._value_optional(row, "verification_summary"),
        )

    def record_operator_request(self, request: OperatorRequest) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                RECORD_OPERATOR_REQUEST_SQL,
                build_record_operator_request_params(request),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

    def list_operator_requests(
        self,
        *,
        repo: str,
        epic_issue_number: int | None = None,
        include_closed: bool = False,
    ) -> list[OperatorRequest]:
        sql, params = build_list_operator_requests_query(
            repo=repo,
            epic_issue_number=epic_issue_number,
            include_closed=include_closed,
        )
        with self._connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [self._row_to_operator_request(row) for row in rows]

    def close_operator_request(
        self,
        *,
        repo: str,
        epic_issue_number: int,
        reason_code: str,
        closed_reason: str,
    ) -> OperatorRequest | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                CLOSE_OPERATOR_REQUEST_SQL,
                (closed_reason, repo, epic_issue_number, reason_code),
            )
            row = cursor.fetchone()
        self._connection.commit()
        if row is None:
            return None
        return self._row_to_operator_request(row)

    def record_story_pull_request_link(self, link: StoryPullRequestLink) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO story_pull_request_link (
                    repo,
                    story_issue_number,
                    pull_number,
                    pull_url
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (repo, story_issue_number) DO UPDATE SET
                    pull_number = EXCLUDED.pull_number,
                    pull_url = EXCLUDED.pull_url
                RETURNING id
                """,
                (
                    link.repo,
                    link.story_issue_number,
                    link.pull_number,
                    link.pull_url,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

    def get_story_pull_request_link(
        self, *, repo: str, story_issue_number: int
    ) -> dict[str, Any] | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT repo, story_issue_number, pull_number, pull_url
                FROM story_pull_request_link
                WHERE repo = %s AND story_issue_number = %s
                """,
                (repo, story_issue_number),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "repo": self._value(row, "repo"),
            "story_issue_number": self._value(row, "story_issue_number"),
            "pull_number": self._value(row, "pull_number"),
            "pull_url": self._value(row, "pull_url"),
        }

    def record_task_spec_draft(self, draft: TaskSpecDraft) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO story_task_draft (
                    repo,
                    story_issue_number,
                    title,
                    complexity,
                    goal,
                    allowed_paths_json,
                    dod_json,
                    verification_json,
                    references_json,
                    status,
                    source_reason_code
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (
                    draft.repo,
                    draft.story_issue_number,
                    draft.title,
                    draft.complexity,
                    draft.goal,
                    json.dumps(list(draft.allowed_paths)),
                    json.dumps(list(draft.dod)),
                    json.dumps(list(draft.verification)),
                    json.dumps(list(draft.references)),
                    draft.status,
                    draft.source_reason_code,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

    def record_natural_language_intent(
        self, intent: NaturalLanguageIntent
    ) -> str | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                RECORD_NATURAL_LANGUAGE_INTENT_SQL,
                build_record_natural_language_intent_params(intent),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else str(self._value(row, "id"))

    def update_natural_language_intent(self, intent: NaturalLanguageIntent) -> None:
        self.record_natural_language_intent(intent)

    def get_natural_language_intent(
        self, intent_id: str
    ) -> NaturalLanguageIntent | None:
        with self._connection.cursor() as cursor:
            cursor.execute(build_get_natural_language_intent_query(), (intent_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return row_to_natural_language_intent(row)

    def list_natural_language_intents(
        self, *, repo: str
    ) -> list[NaturalLanguageIntent]:
        with self._connection.cursor() as cursor:
            cursor.execute(build_list_natural_language_intents_query(), (repo,))
            rows = cursor.fetchall()
        return [row_to_natural_language_intent(row) for row in rows]

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
        next_action_json: dict[str, Any] | None = None,
        milestones_json: list[dict[str, Any]] | None = None,
        plan_version: int = 1,
        supersedes_plan_id: str | None = None,
        replan_events_json: list[dict[str, Any]] | None = None,
        completion_contract_json: dict[str, Any] | None = None,
    ) -> OrchestratorSession:
        session_id = f"orch-{uuid.uuid4().hex[:12]}"
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO orchestrator_session (
                    id, repo, host_tool, started_by, status, watch_scope_json,
                    current_phase, objective_summary, plan_summary, handoff_summary,
                    next_action_json, milestones_json, plan_version,
                    supersedes_plan_id, replan_events_json, completion_contract_json
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING id, repo, host_tool, started_by, status, watch_scope_json,
                          current_phase, objective_summary, plan_summary, handoff_summary,
                          next_action_json, milestones_json, plan_version,
                          supersedes_plan_id, replan_events_json, completion_contract_json,
                          created_at, updated_at
                """,
                (
                    session_id,
                    repo,
                    host_tool,
                    started_by,
                    "active",
                    json.dumps(watch_scope_json or {}),
                    current_phase,
                    objective_summary,
                    plan_summary,
                    handoff_summary,
                    json.dumps(next_action_json or {}),
                    json.dumps(milestones_json or []),
                    int(plan_version or 1),
                    supersedes_plan_id,
                    json.dumps(replan_events_json or []),
                    json.dumps(completion_contract_json or {}),
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return self._row_to_orchestrator_session(row)

    def get_orchestrator_session(self, session_id: str) -> OrchestratorSession | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repo, host_tool, started_by, status, watch_scope_json,
                       current_phase, objective_summary, plan_summary, handoff_summary,
                       next_action_json, milestones_json, plan_version,
                       supersedes_plan_id, replan_events_json, completion_contract_json,
                       created_at, updated_at
                FROM orchestrator_session
                WHERE id = %s
                """,
                (session_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_orchestrator_session(row)

    def update_orchestrator_session_scope(
        self, *, session_id: str, watch_scope_json: dict[str, Any]
    ) -> OrchestratorSession:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orchestrator_session
                SET watch_scope_json = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, repo, host_tool, started_by, status, watch_scope_json,
                          current_phase, objective_summary, plan_summary, handoff_summary,
                          next_action_json, milestones_json, plan_version,
                          supersedes_plan_id, replan_events_json, completion_contract_json,
                          created_at, updated_at
                """,
                (json.dumps(watch_scope_json), session_id),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return self._row_to_orchestrator_session(row)

    def set_orchestrator_session_status(
        self, *, session_id: str, status: str
    ) -> OrchestratorSession:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE orchestrator_session
                SET status = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, repo, host_tool, started_by, status, watch_scope_json,
                          current_phase, objective_summary, plan_summary, handoff_summary,
                          next_action_json, milestones_json, plan_version,
                          supersedes_plan_id, replan_events_json, completion_contract_json,
                          created_at, updated_at
                """,
                (status, session_id),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return self._row_to_orchestrator_session(row)

    def record_orchestrator_session_job(
        self, *, session_id: str, job: dict[str, Any]
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_job (
                    id, repo, job_kind, status, story_issue_number, work_id,
                    worker_name, pid, command, log_path, orchestrator_session_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    orchestrator_session_id = EXCLUDED.orchestrator_session_id
                """,
                (
                    int(job.get("id") or 0),
                    str(job.get("repo") or ""),
                    str(job.get("job_kind") or "unknown"),
                    str(job.get("status") or "running"),
                    job.get("story_issue_number"),
                    job.get("work_id"),
                    str(job.get("worker_name") or f"orchestrator-{session_id}"),
                    job.get("pid"),
                    str(job.get("command") or "orchestrator-session"),
                    str(job.get("log_path") or ""),
                    session_id,
                ),
            )
        self._connection.commit()

    def list_orchestrator_session_jobs(self, session_id: str) -> list[dict[str, Any]]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, repo, job_kind, status, story_issue_number, work_id,
                       worker_name, pid, command, log_path, orchestrator_session_id
                FROM execution_job
                WHERE orchestrator_session_id = %s
                ORDER BY id
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def promote_natural_language_proposal(
        self,
        *,
        intent_id: str,
        proposal: dict[str, Any],
        approver: str,
        promotion_mode: str | None = None,
    ) -> int:
        intent = self.get_natural_language_intent(intent_id)
        if intent is None:
            raise KeyError(intent_id)

        with self._connection.cursor() as cursor:
            epic_issue_number = promote_intent_proposal_via_cursor(
                cursor=cursor,
                intent=intent,
                intent_id=intent_id,
                approver=approver,
                proposal=proposal,
                promotion_mode=promotion_mode,
                intake_epic_start=INTAKE_EPIC_START,
                intake_story_start=INTAKE_STORY_START,
                value_reader=self._value,
            )
        self._connection.commit()
        self.sync_ready_states()
        return epic_issue_number

    def record_approval_event(self, event: ApprovalEvent) -> int | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO approval_event (
                    work_id,
                    approver,
                    decision,
                    reason
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    event.work_id,
                    event.approver,
                    event.decision,
                    event.reason,
                ),
            )
            row = cursor.fetchone()
        self._connection.commit()
        return None if row is None else int(self._value(row, "id"))

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
        apply_finalization_status_update(
            update_work_status=self.update_work_status,
            work_id=work_id,
            status=status,
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
        record_finalization_followups(
            record_run=self.record_run,
            record_verification=self.record_verification,
            record_commit_link=self.record_commit_link,
            record_pull_request_link=self.record_pull_request_link,
            execution_run=execution_run,
            verification=verification,
            commit_link=commit_link,
            pull_request_link=pull_request_link,
        )

    def _has_successful_terminal_run(self, work_id: str) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM execution_run
                WHERE work_id = %s
                  AND status = 'done'
                LIMIT 1
                """,
                (work_id,),
            )
            return cursor.fetchone() is not None

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
        self.record_run(
            ExecutionRun(
                work_id=work_id,
                worker_name="guardrails",
                status="blocked",
                summary=message,
            )
        )

    def _row_to_work_item(self, row: Any) -> WorkItem:
        return row_to_work_item(row)

    def _row_to_program_story(self, row: Any) -> ProgramStory:
        return row_to_program_story(row)

    def _row_to_work_claim(self, row: Any) -> WorkClaim:
        return row_to_work_claim(row)

    def _row_to_operator_request(self, row: Any) -> OperatorRequest:
        return row_to_operator_request(row)

    def _row_to_orchestrator_session(self, row: Any) -> OrchestratorSession:
        return OrchestratorSession(
            id=str(self._value(row, "id")),
            repo=str(self._value(row, "repo")),
            host_tool=str(self._value(row, "host_tool")),
            started_by=str(self._value(row, "started_by")),
            status=cast(Any, _orchestrator_session_status(self._value(row, "status"))),
            watch_scope_json=dict(self._value_optional(row, "watch_scope_json") or {}),
            current_phase=cast(
                Any,
                _orchestrator_session_phase(
                    self._value_optional(row, "current_phase") or "observe"
                ),
            ),
            objective_summary=self._value_optional(row, "objective_summary"),
            plan_summary=self._value_optional(row, "plan_summary"),
            handoff_summary=self._value_optional(row, "handoff_summary"),
            next_action_json=dict(self._value_optional(row, "next_action_json") or {}),
            milestones_json=list(self._value_optional(row, "milestones_json") or []),
            plan_version=int(self._value_optional(row, "plan_version") or 1),
            supersedes_plan_id=self._value_optional(row, "supersedes_plan_id"),
            replan_events_json=list(
                self._value_optional(row, "replan_events_json") or []
            ),
            completion_contract_json=dict(
                self._value_optional(row, "completion_contract_json") or {}
            ),
            created_at=self._value_optional(row, "created_at"),
            updated_at=self._value_optional(row, "updated_at"),
        )

    def _value(self, row: Any, key: str) -> Any:
        return value(row, key)

    def _value_optional(self, row: Any, key: str) -> Any:
        return value_optional(row, key)
