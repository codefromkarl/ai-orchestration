GET_TASK_DETAIL_QUERY = """
SELECT
    wi.id,
    wi.repo,
    wi.source_issue_number,
    wi.canonical_story_issue_number,
    wi.title,
    wi.lane,
    wi.wave,
    wi.status,
    wi.complexity,
    wi.task_type,
    wi.blocking_mode,
    wi.dod_json,
    wi.attempt_count,
    wi.last_failure_reason,
    wi.next_eligible_at,
    wi.blocked_reason,
    wi.decision_required,
    ps.issue_number AS story_issue_number,
    ps.title AS story_title,
    ps.execution_status AS story_execution_status,
    pe.issue_number AS epic_issue_number,
    pe.title AS epic_title,
    pe.execution_status AS epic_execution_status,
    gin.title AS source_issue_title,
    gin.url AS source_issue_url,
    gin.github_state,
    gin.status_label,
    CASE WHEN vatq.id IS NULL THEN FALSE ELSE TRUE END AS in_active_queue
FROM work_item wi
LEFT JOIN program_story ps
  ON ps.repo = wi.repo
 AND ps.issue_number = wi.canonical_story_issue_number
LEFT JOIN program_epic pe
  ON pe.repo = ps.repo
 AND pe.issue_number = ps.epic_issue_number
LEFT JOIN github_issue_normalized gin
  ON gin.repo = wi.repo
 AND gin.issue_number = wi.source_issue_number
LEFT JOIN v_active_task_queue vatq
  ON vatq.id = wi.id
WHERE wi.repo = %s AND wi.id = %s
"""

GET_TASK_RECENT_RUNS_QUERY = """
SELECT
    er.id,
    er.work_id,
    er.worker_name,
    er.status,
    er.branch_name,
    er.command_digest,
    er.summary,
    er.exit_code,
    er.elapsed_ms,
    er.stdout_digest,
    er.stderr_digest,
    er.result_payload_json,
    er.started_at,
    er.finished_at,
    ve.check_type,
    ve.command AS verification_command,
    ve.passed AS verification_passed,
    ve.output_digest AS verification_output_digest,
    ve.exit_code AS verification_exit_code,
    ve.created_at AS verification_created_at
FROM execution_run er
LEFT JOIN LATERAL (
    SELECT check_type, command, passed, output_digest, exit_code, created_at
    FROM verification_evidence
    WHERE run_id = er.id
    ORDER BY id DESC
    LIMIT 1
) ve ON TRUE
WHERE er.work_id = %s
ORDER BY er.id DESC
LIMIT 10
"""

GET_TASK_CLAIM_QUERY = """
SELECT work_id, worker_name, workspace_path, branch_name, lease_expires_at, claimed_at, claimed_paths
FROM work_claim
WHERE work_id = %s
"""

GET_TASK_APPROVAL_EVENTS_QUERY = """
SELECT id, approver, decision, reason, created_at
FROM approval_event
WHERE work_id = %s
ORDER BY id DESC
"""

GET_TASK_COMMIT_LINK_QUERY = """
SELECT repo, issue_number, commit_sha, commit_message, created_at
FROM work_commit_link
WHERE work_id = %s
"""

GET_TASK_PULL_REQUESTS_QUERY = """
SELECT id, repo, pr_number, pr_url, review_state, created_at
FROM pull_request_link
WHERE work_id = %s
ORDER BY id DESC
"""

GET_TASK_JOBS_QUERY = """
SELECT id, job_kind, status, story_issue_number, work_id, worker_name, pid, command, log_path, started_at, finished_at, exit_code
FROM execution_job
WHERE repo = %s AND work_id = %s
ORDER BY started_at DESC, id DESC
"""

GET_TASK_SESSIONS_QUERY = """
SELECT
    es.id,
    es.status,
    es.attempt_index,
    es.current_phase,
    es.waiting_reason,
    es.created_at,
    es.updated_at,
    ck.phase AS last_checkpoint_phase,
    ck.phase_index AS last_checkpoint_index,
    ck.summary AS last_checkpoint_summary,
    ck.next_action_hint AS last_checkpoint_next_action
FROM execution_session es
LEFT JOIN execution_checkpoint ck
  ON ck.id = es.last_checkpoint_id
WHERE es.work_id = %s
ORDER BY es.updated_at DESC, es.created_at DESC
LIMIT 5
"""

GET_TASK_ARTIFACTS_QUERY = """
SELECT
    id,
    session_id,
    run_id,
    artifact_type,
    artifact_key,
    mime_type,
    content_size_bytes,
    metadata,
    created_at
FROM artifact
WHERE work_id = %s
ORDER BY created_at DESC, id DESC
LIMIT 8
"""

LIST_RUNTIME_OBSERVABILITY_QUERY = """
SELECT
    wi.id AS work_id,
    wi.source_issue_number,
    wi.title,
    wi.status,
    wi.lane,
    wi.wave,
    wi.blocked_reason,
    wi.decision_required,
    wi.last_failure_reason,
    wc.worker_name AS active_claim_worker_name,
    es.id AS session_id,
    es.status AS session_status,
    es.attempt_index AS session_attempt_index,
    es.current_phase AS session_current_phase,
    es.waiting_reason AS session_waiting_reason,
    es.updated_at AS session_updated_at,
    ck.summary AS last_checkpoint_summary,
    ck.next_action_hint AS last_checkpoint_next_action,
    artifact.id AS artifact_id,
    artifact.session_id AS artifact_session_id,
    artifact.run_id AS artifact_run_id,
    artifact.artifact_type,
    artifact.artifact_key,
    artifact.mime_type AS artifact_mime_type,
    artifact.content_size_bytes AS artifact_content_size_bytes,
    artifact.metadata AS artifact_metadata,
    artifact.created_at AS artifact_created_at
FROM work_item wi
LEFT JOIN work_claim wc
  ON wc.work_id = wi.id
LEFT JOIN LATERAL (
    SELECT id, status, attempt_index, current_phase, waiting_reason, updated_at, last_checkpoint_id
    FROM execution_session es
    WHERE es.work_id = wi.id
    ORDER BY es.updated_at DESC, es.created_at DESC
    LIMIT 1
) es ON TRUE
LEFT JOIN execution_checkpoint ck
  ON ck.id = es.last_checkpoint_id
LEFT JOIN LATERAL (
    SELECT id, session_id, run_id, artifact_type, artifact_key, mime_type, content_size_bytes, metadata, created_at
    FROM artifact
    WHERE work_id = wi.id
    ORDER BY created_at DESC, id DESC
    LIMIT 1
) artifact ON TRUE
WHERE wi.repo = %s
  AND (
    es.id IS NOT NULL
    OR artifact.id IS NOT NULL
    OR wi.status IN ('in_progress', 'verifying', 'blocked')
  )
ORDER BY COALESCE(es.updated_at, artifact.created_at) DESC NULLS LAST, wi.id ASC
LIMIT 80
"""
