LIST_WORK_SNAPSHOT_EXPORTS_QUERY = """
SELECT id, repo, title, lane, wave, status, complexity,
       attempt_count, last_failure_reason, next_eligible_at,
       source_issue_number, canonical_story_issue_number,
       task_type, blocking_mode, blocked_reason, decision_required,
       dod_json
FROM work_item
WHERE repo = %s
  AND (%s IS NULL OR id > %s)
ORDER BY id ASC
LIMIT %s
"""


GET_WORK_SNAPSHOT_EXPORT_QUERY = """
SELECT id, repo, title, lane, wave, status, complexity,
       attempt_count, last_failure_reason, next_eligible_at,
       source_issue_number, canonical_story_issue_number,
       task_type, blocking_mode, blocked_reason, decision_required,
       dod_json
FROM work_item
WHERE repo = %s
  AND id = %s
"""


LIST_EXECUTION_ATTEMPT_EXPORTS_QUERY = """
WITH ordered_runs AS (
    SELECT er.id,
           er.work_id,
           er.worker_name,
           er.status,
           er.branch_name,
           er.command_digest,
           er.exit_code,
           er.elapsed_ms,
           er.stdout_digest,
           er.stderr_digest,
           er.result_payload_json,
           er.started_at,
           er.finished_at,
           ROW_NUMBER() OVER (
               PARTITION BY er.work_id
               ORDER BY er.id ASC
           ) AS attempt_number,
           wi.repo
    FROM execution_run er
    JOIN work_item wi ON wi.id = er.work_id
)
SELECT id,
       work_id,
       worker_name,
       status,
       branch_name,
       command_digest,
       exit_code,
       elapsed_ms,
       stdout_digest,
       stderr_digest,
       result_payload_json,
       started_at,
       finished_at,
       attempt_number
FROM ordered_runs
WHERE repo = %s
  AND (%s IS NULL OR id > %s)
ORDER BY id ASC
LIMIT %s
"""


LIST_VERIFICATION_RESULT_EXPORTS_QUERY = """
WITH ordered_runs AS (
    SELECT er.id,
           er.work_id,
           ROW_NUMBER() OVER (
               PARTITION BY er.work_id
               ORDER BY er.id ASC
           ) AS attempt_number,
           wi.repo
    FROM execution_run er
    JOIN work_item wi ON wi.id = er.work_id
)
SELECT ve.id,
       ve.run_id,
       ve.work_id,
       ve.check_type,
       ve.command,
       ve.passed,
       ve.output_digest,
       ve.exit_code,
       ve.elapsed_ms,
       ve.stdout_digest,
       ve.stderr_digest,
       ordered_runs.attempt_number
FROM verification_evidence ve
JOIN ordered_runs
  ON ordered_runs.id = ve.run_id
WHERE ordered_runs.repo = %s
  AND (%s IS NULL OR ve.id > %s)
ORDER BY ve.id ASC
LIMIT %s
"""
