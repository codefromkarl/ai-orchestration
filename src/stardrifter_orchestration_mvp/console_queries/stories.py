GET_STORY_DETAIL_QUERY = """
SELECT
    ps.issue_number AS story_issue_number,
    ps.repo,
    ps.epic_issue_number,
    pe.title AS epic_title,
    ps.title,
    ps.lane,
    ps.complexity,
    ps.program_status,
    ps.execution_status,
    ps.active_wave,
    ps.notes,
    spl.pull_number AS story_pull_number,
    spl.pull_url AS story_pull_url,
    sir.merged AS last_merge_succeeded,
    sir.promoted AS last_promotion_succeeded,
    sir.merge_commit_sha,
    sir.promotion_commit_sha,
    sir.blocked_reason AS story_integration_blocked_reason,
    sir.summary AS story_integration_summary,
    sir.created_at AS story_integration_created_at,
    svr.verification_status,
    svr.verification_summary,
    svr.verification_check_type
FROM program_story ps
LEFT JOIN program_epic pe
  ON pe.repo = ps.repo
 AND pe.issue_number = ps.epic_issue_number
LEFT JOIN story_pull_request_link spl
  ON spl.repo = ps.repo
 AND spl.story_issue_number = ps.issue_number
LEFT JOIN LATERAL (
    SELECT merged, promoted, merge_commit_sha, promotion_commit_sha, blocked_reason, summary, created_at
    FROM story_integration_run
    WHERE repo = ps.repo
      AND story_issue_number = ps.issue_number
    ORDER BY id DESC
    LIMIT 1
) sir ON TRUE
LEFT JOIN LATERAL (
    SELECT
        CASE WHEN passed THEN 'passed' ELSE 'failed' END AS verification_status,
        summary AS verification_summary,
        check_type AS verification_check_type
    FROM story_verification_run
    WHERE repo = ps.repo
      AND story_issue_number = ps.issue_number
    ORDER BY id DESC
    LIMIT 1
) svr ON TRUE
WHERE ps.repo = %s AND ps.issue_number = %s
"""

GET_STORY_DETAIL_QUERY_FALLBACK = """
SELECT
    ps.issue_number AS story_issue_number,
    ps.repo,
    ps.epic_issue_number,
    pe.title AS epic_title,
    ps.title,
    ps.lane,
    ps.complexity,
    ps.program_status,
    ps.execution_status,
    ps.active_wave,
    ps.notes,
    spl.pull_number AS story_pull_number,
    spl.pull_url AS story_pull_url,
    sir.merged AS last_merge_succeeded,
    sir.promoted AS last_promotion_succeeded,
    sir.merge_commit_sha,
    sir.promotion_commit_sha,
    sir.blocked_reason AS story_integration_blocked_reason,
    sir.summary AS story_integration_summary,
    sir.created_at AS story_integration_created_at,
    NULL::text AS verification_status,
    NULL::text AS verification_summary,
    NULL::text AS verification_check_type
FROM program_story ps
LEFT JOIN program_epic pe
  ON pe.repo = ps.repo
 AND pe.issue_number = ps.epic_issue_number
LEFT JOIN story_pull_request_link spl
  ON spl.repo = ps.repo
 AND spl.story_issue_number = ps.issue_number
LEFT JOIN LATERAL (
    SELECT merged, promoted, merge_commit_sha, promotion_commit_sha, blocked_reason, summary, created_at
    FROM story_integration_run
    WHERE repo = ps.repo
      AND story_issue_number = ps.issue_number
    ORDER BY id DESC
    LIMIT 1
) sir ON TRUE
WHERE ps.repo = %s AND ps.issue_number = %s
"""

GET_STORY_TASKS_QUERY = """
SELECT
    wi.id AS work_id,
    wi.source_issue_number,
    wi.title,
    wi.status,
    wi.task_type,
    wi.blocking_mode,
    wi.wave,
    wi.lane,
    wi.blocked_reason,
    wi.decision_required,
    wi.attempt_count,
    wi.last_failure_reason,
    wi.next_eligible_at,
    CASE WHEN vatq.id IS NULL THEN FALSE ELSE TRUE END AS in_active_queue
FROM work_item wi
LEFT JOIN v_active_task_queue vatq
  ON vatq.id = wi.id
WHERE wi.repo = %s
  AND wi.canonical_story_issue_number = %s
ORDER BY wi.source_issue_number, wi.id
"""

GET_STORY_DRAFTS_QUERY = """
SELECT
    id,
    title,
    complexity,
    goal,
    allowed_paths_json,
    dod_json,
    verification_json,
    references_json,
    status,
    source_reason_code,
    created_at,
    updated_at
FROM story_task_draft
WHERE repo = %s AND story_issue_number = %s
ORDER BY id DESC
"""

GET_STORY_DEPENDENCIES_QUERY = """
SELECT
    psd.depends_on_story_issue_number AS story_issue_number,
    dep.title,
    dep.execution_status,
    'depends_on' AS direction
FROM program_story_dependency psd
JOIN program_story dep
  ON dep.repo = psd.repo
 AND dep.issue_number = psd.depends_on_story_issue_number
WHERE psd.repo = %s AND psd.story_issue_number = %s
UNION ALL
SELECT
    psd.story_issue_number AS story_issue_number,
    dep.title,
    dep.execution_status,
    'required_by' AS direction
FROM program_story_dependency psd
JOIN program_story dep
  ON dep.repo = psd.repo
 AND dep.issue_number = psd.story_issue_number
WHERE psd.repo = %s AND psd.depends_on_story_issue_number = %s
ORDER BY direction, story_issue_number
"""

GET_STORY_RUNNING_JOBS_QUERY = """
SELECT id, job_kind, status, story_issue_number, work_id, worker_name, pid, command, log_path, started_at
FROM execution_job
WHERE repo = %s
  AND story_issue_number = %s
ORDER BY started_at DESC, id DESC
"""

GET_STORY_DECOMPOSITION_QUEUE_QUERY = """
SELECT repo, epic_issue_number, epic_title, story_issue_number, story_title, execution_status, story_task_count
FROM v_story_decomposition_queue
WHERE repo = %s AND story_issue_number = %s
"""
