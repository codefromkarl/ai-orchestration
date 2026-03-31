"""
PostgreSQL implementation of ControlPlaneRepository.

This module provides the main production repository implementation using PostgreSQL.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import replace
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
)
from ._postgres_row_mapping import (
    row_to_operator_request,
    row_to_program_story,
    row_to_work_claim,
    row_to_work_item,
    value,
    value_optional,
)

LEASE_DURATION = timedelta(minutes=15)


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
                """
                UPDATE program_epic
                SET execution_status = %s,
                    updated_at = NOW()
                WHERE repo = %s AND issue_number = %s
                """,
                (execution_status, repo, issue_number),
            )
        self._connection.commit()

    def set_program_epic_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE program_epic
                SET execution_status = %s,
                    updated_at = NOW()
                WHERE repo = %s AND issue_number = %s
                """,
                (execution_status, repo, issue_number),
            )
            cursor.execute(
                """
                WITH direct_storys AS (
                    SELECT ps.issue_number
                    FROM program_story ps
                    WHERE ps.repo = %s
                      AND ps.epic_issue_number = %s
                ),
                dependency_state AS (
                    SELECT
                        ds.issue_number,
                        COUNT(psd.depends_on_story_issue_number) AS dependency_count,
                        COUNT(*) FILTER (
                            WHERE dep.execution_status NOT IN ('active', 'done')
                        ) AS unmet_dependencies
                    FROM direct_storys ds
                    LEFT JOIN program_story_dependency psd
                      ON psd.repo = %s
                     AND psd.story_issue_number = ds.issue_number
                    LEFT JOIN program_story dep
                      ON dep.repo = psd.repo
                     AND dep.issue_number = psd.depends_on_story_issue_number
                    GROUP BY ds.issue_number
                ),
                task_counts AS (
                    SELECT
                        ds.issue_number,
                        COUNT(wi.id) AS task_count
                    FROM direct_storys ds
                    LEFT JOIN work_item wi
                      ON wi.repo = %s
                     AND wi.canonical_story_issue_number = ds.issue_number
                    GROUP BY ds.issue_number
                )
                UPDATE program_story ps
                SET execution_status = CASE
                        WHEN %s = 'active' AND ds.unmet_dependencies = 0 AND tc.task_count > 0 THEN 'active'::execution_status
                        WHEN %s = 'active' AND ds.unmet_dependencies = 0 THEN 'decomposing'::execution_status
                        WHEN %s = 'active' THEN 'gated'::execution_status
                        ELSE %s::execution_status
                    END,
                    updated_at = NOW()
                FROM dependency_state ds
                JOIN task_counts tc
                  ON tc.issue_number = ds.issue_number
                WHERE ps.repo = %s
                  AND ps.issue_number = ds.issue_number
                """,
                (
                    repo,
                    issue_number,
                    repo,
                    repo,
                    execution_status,
                    execution_status,
                    execution_status,
                    "backlog"
                    if execution_status in {"backlog", "planned"}
                    else execution_status,
                    repo,
                ),
            )
        self._connection.commit()

    def set_program_story_execution_status(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE program_story
                SET execution_status = %s,
                    updated_at = NOW()
                WHERE repo = %s AND issue_number = %s
                """,
                (execution_status, repo, issue_number),
            )
        self._connection.commit()

    def set_program_story_execution_status_with_propagation(
        self, *, repo: str, issue_number: int, execution_status: str
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE program_story
                SET execution_status = %s,
                    updated_at = NOW()
                WHERE repo = %s AND issue_number = %s
                """,
                (execution_status, repo, issue_number),
            )
            cursor.execute(
                """
                WITH current_story AS (
                    SELECT epic_issue_number
                    FROM program_story
                    WHERE repo = %s AND issue_number = %s
                ),
                sibling_storys AS (
                    SELECT ps.issue_number
                    FROM program_story ps
                    JOIN current_story cs ON cs.epic_issue_number = ps.epic_issue_number
                    JOIN program_story_dependency psd
                      ON psd.repo = ps.repo
                     AND psd.story_issue_number = ps.issue_number
                     AND psd.depends_on_story_issue_number = %s
                    WHERE ps.repo = %s
                ),
                dependency_state AS (
                    SELECT
                        ss.issue_number,
                        COUNT(*) FILTER (
                            WHERE dep.execution_status NOT IN ('active', 'done')
                        ) AS unmet_dependencies
                    FROM sibling_storys ss
                    JOIN program_story_dependency psd
                      ON psd.repo = %s
                     AND psd.story_issue_number = ss.issue_number
                    JOIN program_story dep
                      ON dep.repo = psd.repo
                     AND dep.issue_number = psd.depends_on_story_issue_number
                    GROUP BY ss.issue_number
                ),
                task_counts AS (
                    SELECT
                        ss.issue_number,
                        COUNT(wi.id) AS task_count
                    FROM sibling_storys ss
                    LEFT JOIN work_item wi
                      ON wi.repo = %s
                     AND wi.canonical_story_issue_number = ss.issue_number
                    GROUP BY ss.issue_number
                )
                UPDATE program_story ps
                SET execution_status = CASE
                        WHEN %s = 'done' AND ds.unmet_dependencies = 0 AND tc.task_count > 0 THEN 'active'::execution_status
                        WHEN %s = 'done' AND ds.unmet_dependencies = 0 THEN 'decomposing'::execution_status
                        ELSE ps.execution_status
                    END,
                    updated_at = NOW()
                FROM dependency_state ds
                JOIN task_counts tc
                  ON tc.issue_number = ds.issue_number
                WHERE ps.repo = %s
                  AND ps.issue_number = ds.issue_number
                """,
                (
                    repo,
                    issue_number,
                    issue_number,
                    repo,
                    repo,
                    repo,
                    execution_status,
                    execution_status,
                    repo,
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
            # Step 1: Return in-progress items to pending if no active claim
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

            # Step 2: Auto-repair missing repo from program_story
            # Repairs data before blocking, reducing manual intervention
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

            # Step 3: Auto-repair missing/unassigned wave from parent Epic/Story
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

            # Step 4: Block work items with data integrity issues (after repair attempt)
            # These items cannot be executed until their data is fixed
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

            # Step 5: Evaluate readiness for items that pass integrity checks
            cursor.execute(
                """
                WITH ready_eval AS (
                    SELECT
                        wi.id,
                        (
                            (wi.next_eligible_at IS NULL OR wi.next_eligible_at <= NOW())
                            AND
                            (
                                wi.canonical_story_issue_number IS NULL
                                OR EXISTS (
                                    SELECT 1
                                    FROM program_story current_story
                                    WHERE current_story.repo = wi.repo
                                      AND current_story.issue_number = wi.canonical_story_issue_number
                                      AND current_story.execution_status IN ('active', 'done')
                                )
                            )
                            AND
                            NOT EXISTS (
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
                        ) AS is_ready
                    FROM work_item wi
                    WHERE wi.status IN ('pending', 'ready')
                      -- Data integrity pre-check: skip items with known issues
                      AND wi.repo IS NOT NULL
                      AND wi.wave IS NOT NULL
                )
                UPDATE work_item wi
                SET status = CASE
                        WHEN ready_eval.is_ready THEN 'ready'::work_status
                        ELSE 'pending'::work_status
                    END,
                    updated_at = NOW()
                FROM ready_eval
                WHERE wi.id = ready_eval.id
                  AND (
                    (wi.status = 'pending' AND ready_eval.is_ready)
                    OR (wi.status = 'ready' AND NOT ready_eval.is_ready)
                  )
                """
            )
        self._connection.commit()

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
                """
                WITH claim_input AS (
                    SELECT
                        %s::text AS work_id,
                        %s::text AS worker_name,
                        %s::text AS workspace_path,
                        %s::text AS branch_name,
                        %s::text AS lease_token,
                        %s::timestamptz AS lease_expires_at,
                        %s::jsonb AS claimed_paths
                ),
                locked AS (
                    SELECT wi.id
                    FROM work_item wi
                    CROSS JOIN claim_input ci
                    WHERE wi.id = ci.work_id
                      AND wi.status = 'ready'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM work_claim wc
                          CROSS JOIN LATERAL jsonb_array_elements_text(wc.claimed_paths) AS existing(path)
                          CROSS JOIN LATERAL jsonb_array_elements_text(ci.claimed_paths) AS incoming(path)
                          WHERE wc.work_id <> ci.work_id
                            AND (wc.lease_expires_at IS NULL OR wc.lease_expires_at > NOW())
                            AND (
                                existing.path = incoming.path
                                OR existing.path LIKE incoming.path || '/%%'
                                OR incoming.path LIKE existing.path || '/%%'
                            )
                      )
                    FOR UPDATE SKIP LOCKED
                ),
                updated AS (
                    UPDATE work_item wi
                    SET status = 'in_progress',
                        updated_at = NOW()
                    FROM locked
                    WHERE wi.id = locked.id
                    RETURNING wi.id, wi.title, wi.lane, wi.wave, wi.status, wi.complexity,
                              wi.source_issue_number, wi.dod_json, wi.canonical_story_issue_number,
                              wi.task_type, wi.blocking_mode, wi.blocked_reason, wi.decision_required
                ),
                claim_upsert AS (
                    INSERT INTO work_claim (
                        work_id,
                        worker_name,
                        workspace_path,
                        branch_name,
                        lease_token,
                        lease_expires_at,
                        claimed_paths
                    )
                    SELECT
                        ci.work_id,
                        ci.worker_name,
                        ci.workspace_path,
                        ci.branch_name,
                        ci.lease_token,
                        ci.lease_expires_at,
                        ci.claimed_paths
                    FROM claim_input ci
                    JOIN updated u ON u.id = ci.work_id
                    ON CONFLICT (work_id) DO UPDATE SET
                        worker_name = EXCLUDED.worker_name,
                        workspace_path = EXCLUDED.workspace_path,
                        branch_name = EXCLUDED.branch_name,
                        lease_token = EXCLUDED.lease_token,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        claimed_paths = EXCLUDED.claimed_paths,
                        claimed_at = NOW()
                    RETURNING work_id
                )
                SELECT * FROM updated
                """,
                (
                    work_id,
                    worker_name,
                    workspace_path,
                    branch_name,
                    secrets.token_hex(16),
                    (datetime.now(UTC) + LEASE_DURATION).isoformat(),
                    json.dumps(list(claimed_paths)),
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

    def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
        with self._connection.cursor() as cursor:
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
                """
                INSERT INTO operator_request (
                    repo,
                    epic_issue_number,
                    reason_code,
                    summary,
                    remaining_story_issue_numbers_json,
                    blocked_story_issue_numbers_json,
                    status,
                    opened_at,
                    closed_at,
                    closed_reason
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    request.repo,
                    request.epic_issue_number,
                    request.reason_code,
                    request.summary,
                    json.dumps(list(request.remaining_story_issue_numbers)),
                    json.dumps(list(request.blocked_story_issue_numbers)),
                    request.status,
                    request.opened_at,
                    request.closed_at,
                    request.closed_reason,
                ),
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
        params: tuple[object, ...]
        where_clauses = ["repo = %s"]
        params = (repo,)
        if epic_issue_number is not None:
            where_clauses.append("epic_issue_number = %s")
            params = (repo, epic_issue_number)
        if not include_closed:
            where_clauses.append("status = 'open'")
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT repo,
                       epic_issue_number,
                       reason_code,
                       summary,
                       remaining_story_issue_numbers_json,
                       blocked_story_issue_numbers_json,
                       status,
                       opened_at,
                       closed_at,
                       closed_reason
                FROM operator_request
                WHERE {" AND ".join(where_clauses)}
                ORDER BY opened_at ASC, id ASC
                """,
                params,
            )
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
                """
                WITH closed_request AS (
                    UPDATE operator_request
                    SET status = 'closed',
                        closed_at = NOW(),
                        closed_reason = %s
                    WHERE repo = %s
                      AND epic_issue_number = %s
                      AND reason_code = %s
                      AND status = 'open'
                    RETURNING repo,
                              epic_issue_number,
                              reason_code,
                              summary,
                              remaining_story_issue_numbers_json,
                              blocked_story_issue_numbers_json,
                              status,
                              opened_at,
                              closed_at,
                              closed_reason
                ),
                synced_epic_state AS (
                    UPDATE epic_execution_state ees
                    SET operator_attention_required = EXISTS (
                            SELECT 1
                            FROM operator_request orq
                            JOIN closed_request cr
                              ON cr.repo = orq.repo
                             AND cr.epic_issue_number = orq.epic_issue_number
                            WHERE orq.status = 'open'
                        ),
                        last_operator_action_at = cr.closed_at,
                        last_operator_action_reason = cr.closed_reason,
                        updated_at = NOW()
                    FROM closed_request cr
                    WHERE ees.repo = cr.repo
                      AND ees.epic_issue_number = cr.epic_issue_number
                )
                SELECT repo,
                       epic_issue_number,
                       reason_code,
                       summary,
                       remaining_story_issue_numbers_json,
                       blocked_story_issue_numbers_json,
                       status,
                       opened_at,
                       closed_at,
                       closed_reason
                FROM closed_request
                """,
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
        self.update_work_status(
            work_id,
            status,
            blocked_reason=blocked_reason,
            decision_required=decision_required,
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

    def _value(self, row: Any, key: str) -> Any:
        return value(row, key)

    def _value_optional(self, row: Any, key: str) -> Any:
        return value_optional(row, key)
