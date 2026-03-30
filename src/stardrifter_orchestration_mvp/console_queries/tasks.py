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
