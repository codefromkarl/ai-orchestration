LIST_RUNNING_JOBS_QUERY = """
SELECT
    ej.id,
    ej.repo,
    ej.job_kind,
    ej.status,
    ej.story_issue_number,
    ej.work_id,
    ej.launch_backend,
    ej.worker_name,
    ej.pid,
    ej.command,
    ej.log_path,
    ej.started_at,
    ej.finished_at,
    ej.exit_code,
    ps.title AS story_title,
    ps.execution_status AS story_execution_status,
    pe.issue_number AS epic_issue_number,
    pe.title AS epic_title,
    pe.execution_status AS epic_execution_status,
    wi.source_issue_number,
    wi.title AS task_title,
    wi.status AS task_status,
    wi.task_type
FROM execution_job ej
LEFT JOIN program_story ps
  ON ps.repo = ej.repo
 AND ps.issue_number = ej.story_issue_number
LEFT JOIN program_epic pe
  ON pe.repo = ps.repo
 AND pe.issue_number = ps.epic_issue_number
LEFT JOIN work_item wi
  ON wi.repo = ej.repo
 AND wi.id = ej.work_id
WHERE ej.repo = %s
  AND ej.status = 'running'
ORDER BY ej.started_at DESC, ej.id DESC
"""

GET_JOB_DETAIL_QUERY = """
SELECT
    id,
    repo,
    job_kind,
    status,
    story_issue_number,
    work_id,
    launch_backend,
    worker_name,
    pid,
    command,
    log_path,
    started_at,
    finished_at,
    exit_code
FROM execution_job
WHERE repo = %s AND id = %s
"""

GET_JOB_STORY_DETAIL_QUERY = """
SELECT
    ps.issue_number AS story_issue_number,
    ps.title AS story_title,
    ps.execution_status AS story_execution_status,
    pe.issue_number AS epic_issue_number,
    pe.title AS epic_title,
    pe.execution_status AS epic_execution_status
FROM program_story ps
LEFT JOIN program_epic pe
  ON pe.repo = ps.repo
 AND pe.issue_number = ps.epic_issue_number
WHERE ps.repo = %s AND ps.issue_number = %s
"""

GET_JOB_TASK_DETAIL_QUERY = """
SELECT
    wi.id AS work_id,
    wi.source_issue_number,
    wi.title,
    wi.status,
    wi.task_type,
    wi.attempt_count,
    wi.last_failure_reason,
    wi.next_eligible_at
FROM work_item wi
WHERE wi.repo = %s AND wi.id = %s
"""
