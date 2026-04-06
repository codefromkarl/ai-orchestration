from __future__ import annotations

import json

CLAIM_READY_WORK_ITEM_SQL = """
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
"""


def build_claim_ready_work_item_params(
    *,
    work_id: str,
    worker_name: str,
    workspace_path: str,
    branch_name: str,
    claimed_paths: tuple[str, ...],
    lease_token: str,
    lease_expires_at: str,
) -> tuple[object, ...]:
    return (
        work_id,
        worker_name,
        workspace_path,
        branch_name,
        lease_token,
        lease_expires_at,
        json.dumps(list(claimed_paths)),
    )
