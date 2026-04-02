LIST_EPIC_ROWS_QUERY = """
WITH story_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(wi.id) AS task_count,
        COUNT(*) FILTER (WHERE wi.status = 'done') AS done_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'blocked') AS blocked_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'ready') AS ready_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'in_progress') AS in_progress_task_count,
        COUNT(*) FILTER (WHERE wi.decision_required IS TRUE) AS decision_required_task_count
    FROM program_story ps
    LEFT JOIN work_item wi
      ON wi.repo = ps.repo
     AND wi.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_active_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(vatq.id) AS active_queue_task_count
    FROM program_story ps
    LEFT JOIN v_active_task_queue vatq
      ON vatq.repo = ps.repo
      AND vatq.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_counts AS (
    SELECT repo, epic_issue_number, COUNT(*) AS story_count
    FROM program_story
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
task_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COALESCE(SUM(task_count), 0) AS task_count,
        COALESCE(SUM(done_task_count), 0) AS done_task_count,
        COALESCE(SUM(blocked_task_count), 0) AS blocked_task_count,
        COALESCE(SUM(ready_task_count), 0) AS ready_task_count,
        COALESCE(SUM(in_progress_task_count), 0) AS in_progress_task_count,
        COALESCE(SUM(decision_required_task_count), 0) AS decision_required_task_count
    FROM story_task_counts
    GROUP BY repo, epic_issue_number
),
active_task_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COALESCE(SUM(active_queue_task_count), 0) AS active_queue_task_count
    FROM story_active_task_counts
    GROUP BY repo, epic_issue_number
),
story_decomposition_counts AS (
    SELECT repo, epic_issue_number, COUNT(*) AS queued_story_decomposition_count
    FROM v_story_decomposition_queue
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
dependency_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COUNT(*) AS dependency_count
    FROM program_epic_dependency
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
running_job_counts AS (
    SELECT
        pe.repo,
        pe.issue_number AS epic_issue_number,
        COUNT(ej.id) AS running_job_count
    FROM program_epic pe
    JOIN execution_job ej
      ON ej.repo = pe.repo
     AND ej.status = 'running'
     AND (
         (ej.job_kind = 'epic_decomposition' AND ej.story_issue_number = pe.issue_number)
         OR EXISTS (
             SELECT 1
             FROM program_story ps
             WHERE ps.repo = pe.repo
               AND ps.epic_issue_number = pe.issue_number
               AND ej.story_issue_number = ps.issue_number
         )
     )
    GROUP BY pe.repo, pe.issue_number
)
SELECT
    pe.repo,
    pe.issue_number AS epic_issue_number,
    pe.title,
    pe.lane,
    pe.program_status,
    pe.execution_status,
    pe.active_wave,
    pe.notes,
    COALESCE(story_counts.story_count, 0) AS story_count,
    COALESCE(task_counts.task_count, 0) AS task_count,
    COALESCE(task_counts.done_task_count, 0) AS done_task_count,
    COALESCE(task_counts.blocked_task_count, 0) AS blocked_task_count,
    COALESCE(task_counts.ready_task_count, 0) AS ready_task_count,
    COALESCE(task_counts.in_progress_task_count, 0) AS in_progress_task_count,
    COALESCE(task_counts.decision_required_task_count, 0) AS decision_required_task_count,
    COALESCE(active_task_counts.active_queue_task_count, 0) AS active_queue_task_count,
    COALESCE(story_decomposition_counts.queued_story_decomposition_count, 0) AS queued_story_decomposition_count,
    CASE WHEN edq.epic_issue_number IS NULL THEN FALSE ELSE TRUE END AS queued_for_epic_decomposition,
    COALESCE(dependency_counts.dependency_count, 0) AS dependency_count,
    COALESCE(running_job_counts.running_job_count, 0) AS running_job_count,
    ees.status AS execution_state_status,
    ees.verification_status,
    ees.verification_reason_code,
    ees.verification_summary,
    COALESCE(jsonb_array_length(ees.completed_story_issue_numbers_json), 0) AS completed_story_count,
    COALESCE(jsonb_array_length(ees.blocked_story_issue_numbers_json), 0) AS execution_state_blocked_story_count,
    COALESCE(jsonb_array_length(ees.remaining_story_issue_numbers_json), 0) AS remaining_story_count
FROM program_epic pe
LEFT JOIN story_counts
  ON story_counts.repo = pe.repo
 AND story_counts.epic_issue_number = pe.issue_number
LEFT JOIN task_counts
  ON task_counts.repo = pe.repo
 AND task_counts.epic_issue_number = pe.issue_number
LEFT JOIN active_task_counts
  ON active_task_counts.repo = pe.repo
 AND active_task_counts.epic_issue_number = pe.issue_number
LEFT JOIN story_decomposition_counts
  ON story_decomposition_counts.repo = pe.repo
 AND story_decomposition_counts.epic_issue_number = pe.issue_number
LEFT JOIN v_epic_decomposition_queue edq
  ON edq.repo = pe.repo
 AND edq.epic_issue_number = pe.issue_number
LEFT JOIN dependency_counts
  ON dependency_counts.repo = pe.repo
 AND dependency_counts.epic_issue_number = pe.issue_number
LEFT JOIN running_job_counts
  ON running_job_counts.repo = pe.repo
 AND running_job_counts.epic_issue_number = pe.issue_number
LEFT JOIN epic_execution_state ees
  ON ees.repo = pe.repo
 AND ees.epic_issue_number = pe.issue_number
WHERE pe.repo = %s
ORDER BY pe.issue_number
"""

LIST_EPIC_ROWS_FALLBACK_QUERY = """
WITH story_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(wi.id) AS task_count,
        COUNT(*) FILTER (WHERE wi.status = 'done') AS done_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'blocked') AS blocked_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'ready') AS ready_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'in_progress') AS in_progress_task_count,
        COUNT(*) FILTER (WHERE wi.decision_required IS TRUE) AS decision_required_task_count
    FROM program_story ps
    LEFT JOIN work_item wi
      ON wi.repo = ps.repo
     AND wi.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_active_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(vatq.id) AS active_queue_task_count
    FROM program_story ps
    LEFT JOIN v_active_task_queue vatq
      ON vatq.repo = ps.repo
      AND vatq.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_counts AS (
    SELECT repo, epic_issue_number, COUNT(*) AS story_count
    FROM program_story
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
task_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COALESCE(SUM(task_count), 0) AS task_count,
        COALESCE(SUM(done_task_count), 0) AS done_task_count,
        COALESCE(SUM(blocked_task_count), 0) AS blocked_task_count,
        COALESCE(SUM(ready_task_count), 0) AS ready_task_count,
        COALESCE(SUM(in_progress_task_count), 0) AS in_progress_task_count,
        COALESCE(SUM(decision_required_task_count), 0) AS decision_required_task_count
    FROM story_task_counts
    GROUP BY repo, epic_issue_number
),
active_task_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COALESCE(SUM(active_queue_task_count), 0) AS active_queue_task_count
    FROM story_active_task_counts
    GROUP BY repo, epic_issue_number
),
story_decomposition_counts AS (
    SELECT repo, epic_issue_number, COUNT(*) AS queued_story_decomposition_count
    FROM v_story_decomposition_queue
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
dependency_counts AS (
    SELECT
        repo,
        epic_issue_number,
        COUNT(*) AS dependency_count
    FROM program_epic_dependency
    WHERE repo = %s
    GROUP BY repo, epic_issue_number
),
running_job_counts AS (
    SELECT
        pe.repo,
        pe.issue_number AS epic_issue_number,
        COUNT(ej.id) AS running_job_count
    FROM program_epic pe
    JOIN execution_job ej
      ON ej.repo = pe.repo
     AND ej.status = 'running'
     AND (
         (ej.job_kind = 'epic_decomposition' AND ej.story_issue_number = pe.issue_number)
         OR EXISTS (
             SELECT 1
             FROM program_story ps
             WHERE ps.repo = pe.repo
               AND ps.epic_issue_number = pe.issue_number
               AND ej.story_issue_number = ps.issue_number
         )
     )
    GROUP BY pe.repo, pe.issue_number
)
SELECT
    pe.repo,
    pe.issue_number AS epic_issue_number,
    pe.title,
    pe.lane,
    pe.program_status,
    pe.execution_status,
    pe.active_wave,
    pe.notes,
    COALESCE(story_counts.story_count, 0) AS story_count,
    COALESCE(task_counts.task_count, 0) AS task_count,
    COALESCE(task_counts.done_task_count, 0) AS done_task_count,
    COALESCE(task_counts.blocked_task_count, 0) AS blocked_task_count,
    COALESCE(task_counts.ready_task_count, 0) AS ready_task_count,
    COALESCE(task_counts.in_progress_task_count, 0) AS in_progress_task_count,
    COALESCE(task_counts.decision_required_task_count, 0) AS decision_required_task_count,
    COALESCE(active_task_counts.active_queue_task_count, 0) AS active_queue_task_count,
    COALESCE(story_decomposition_counts.queued_story_decomposition_count, 0) AS queued_story_decomposition_count,
    CASE WHEN edq.epic_issue_number IS NULL THEN FALSE ELSE TRUE END AS queued_for_epic_decomposition,
    COALESCE(dependency_counts.dependency_count, 0) AS dependency_count,
    COALESCE(running_job_counts.running_job_count, 0) AS running_job_count,
    NULL::text AS execution_state_status,
    0 AS completed_story_count,
    0 AS execution_state_blocked_story_count,
    0 AS remaining_story_count
FROM program_epic pe
LEFT JOIN story_counts
  ON story_counts.repo = pe.repo
 AND story_counts.epic_issue_number = pe.issue_number
LEFT JOIN task_counts
  ON task_counts.repo = pe.repo
 AND task_counts.epic_issue_number = pe.issue_number
LEFT JOIN active_task_counts
  ON active_task_counts.repo = pe.repo
 AND active_task_counts.epic_issue_number = pe.issue_number
LEFT JOIN story_decomposition_counts
  ON story_decomposition_counts.repo = pe.repo
 AND story_decomposition_counts.epic_issue_number = pe.issue_number
LEFT JOIN v_epic_decomposition_queue edq
  ON edq.repo = pe.repo
 AND edq.epic_issue_number = pe.issue_number
LEFT JOIN dependency_counts
  ON dependency_counts.repo = pe.repo
 AND dependency_counts.epic_issue_number = pe.issue_number
LEFT JOIN running_job_counts
  ON running_job_counts.repo = pe.repo
 AND running_job_counts.epic_issue_number = pe.issue_number
WHERE pe.repo = %s
ORDER BY pe.issue_number
"""

LIST_EPIC_STORY_TREE_QUERY = """
WITH story_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(wi.id) AS task_count,
        COUNT(*) FILTER (WHERE wi.status = 'done') AS done_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'blocked') AS blocked_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'ready') AS ready_task_count,
        COUNT(*) FILTER (WHERE wi.status = 'in_progress') AS in_progress_task_count,
        COUNT(*) FILTER (WHERE wi.decision_required IS TRUE) AS decision_required_task_count
    FROM program_story ps
    LEFT JOIN work_item wi
      ON wi.repo = ps.repo
     AND wi.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_active_task_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        ps.epic_issue_number,
        COUNT(vatq.id) AS active_queue_task_count
    FROM program_story ps
    LEFT JOIN v_active_task_queue vatq
      ON vatq.repo = ps.repo
      AND vatq.canonical_story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number, ps.epic_issue_number
),
story_running_job_counts AS (
    SELECT
        ps.repo,
        ps.issue_number AS story_issue_number,
        COUNT(ej.id) AS running_job_count
    FROM program_story ps
    LEFT JOIN execution_job ej
      ON ej.repo = ps.repo
     AND ej.story_issue_number = ps.issue_number
     AND ej.status = 'running'
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.issue_number
),
story_summaries AS (
    SELECT
        ps.repo,
        ps.epic_issue_number,
        jsonb_agg(
            jsonb_build_object(
                'story_issue_number', ps.issue_number,
                'title', ps.title,
                'lane', ps.lane,
                'complexity', ps.complexity,
                'execution_status', ps.execution_status,
                'program_status', ps.program_status,
                'active_wave', ps.active_wave,
                'task_count', COALESCE(stc.task_count, 0),
                'done_task_count', COALESCE(stc.done_task_count, 0),
                'blocked_task_count', COALESCE(stc.blocked_task_count, 0),
                'ready_task_count', COALESCE(stc.ready_task_count, 0),
                'in_progress_task_count', COALESCE(stc.in_progress_task_count, 0),
                'decision_required_task_count', COALESCE(stc.decision_required_task_count, 0),
                'active_queue_task_count', COALESCE(satc.active_queue_task_count, 0),
                'running_job_count', COALESCE(srjc.running_job_count, 0),
                'queued_for_story_decomposition', CASE WHEN sdc.story_issue_number IS NULL THEN FALSE ELSE TRUE END,
                'task_summaries', COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'work_id', wi.id,
                            'source_issue_number', wi.source_issue_number,
                            'title', wi.title,
                            'status', wi.status,
                            'task_type', wi.task_type,
                            'decision_required', wi.decision_required,
                            'blocked_reason', wi.blocked_reason,
                            'in_active_queue', CASE WHEN vatq.id IS NULL THEN FALSE ELSE TRUE END
                        )
                        ORDER BY wi.source_issue_number, wi.id
                    )
                    FROM work_item wi
                    LEFT JOIN v_active_task_queue vatq
                      ON vatq.id = wi.id
                    WHERE wi.repo = ps.repo
                      AND wi.canonical_story_issue_number = ps.issue_number
                ), '[]'::jsonb)
            )
            ORDER BY ps.issue_number
        ) AS story_summaries_json
    FROM program_story ps
    LEFT JOIN story_task_counts stc
      ON stc.repo = ps.repo
     AND stc.story_issue_number = ps.issue_number
    LEFT JOIN story_active_task_counts satc
      ON satc.repo = ps.repo
     AND satc.story_issue_number = ps.issue_number
    LEFT JOIN story_running_job_counts srjc
      ON srjc.repo = ps.repo
     AND srjc.story_issue_number = ps.issue_number
    LEFT JOIN v_story_decomposition_queue sdc
      ON sdc.repo = ps.repo
     AND sdc.story_issue_number = ps.issue_number
    WHERE ps.repo = %s
    GROUP BY ps.repo, ps.epic_issue_number
)
SELECT
    pe.issue_number AS epic_issue_number,
    pe.title,
    COALESCE(story_summaries.story_summaries_json, '[]'::jsonb) AS story_summaries
FROM program_epic pe
LEFT JOIN story_summaries
  ON story_summaries.repo = pe.repo
 AND story_summaries.epic_issue_number = pe.issue_number
WHERE pe.repo = %s
ORDER BY pe.issue_number
"""

GET_EPIC_DETAIL_QUERY = """
SELECT issue_number, repo, title, lane, program_status, execution_status, active_wave, notes
FROM program_epic
WHERE repo = %s AND issue_number = %s
"""

GET_EPIC_STORIES_QUERY = """
SELECT
    ps.issue_number AS story_issue_number,
    ps.title,
    ps.lane,
    ps.complexity,
    ps.program_status,
    ps.execution_status,
    ps.active_wave,
    ps.notes,
    COALESCE(task_counts.task_count, 0) AS task_count,
    COALESCE(task_counts.done_task_count, 0) AS done_task_count,
    COALESCE(task_counts.blocked_task_count, 0) AS blocked_task_count,
    COALESCE(task_counts.ready_task_count, 0) AS ready_task_count,
    COALESCE(active_tasks.active_queue_task_count, 0) AS active_queue_task_count,
    CASE WHEN sdc.story_issue_number IS NULL THEN FALSE ELSE TRUE END AS queued_for_story_decomposition,
    spl.pull_number AS story_pull_number,
    spl.pull_url AS story_pull_url
FROM program_story ps
LEFT JOIN (
    SELECT
        repo,
        canonical_story_issue_number AS story_issue_number,
        COUNT(*) AS task_count,
        COUNT(*) FILTER (WHERE status = 'done') AS done_task_count,
        COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_task_count,
        COUNT(*) FILTER (WHERE status = 'ready') AS ready_task_count
    FROM work_item
    WHERE canonical_story_issue_number IS NOT NULL
    GROUP BY repo, canonical_story_issue_number
) task_counts
  ON task_counts.repo = ps.repo
 AND task_counts.story_issue_number = ps.issue_number
LEFT JOIN (
    SELECT
        repo,
        canonical_story_issue_number AS story_issue_number,
        COUNT(*) AS active_queue_task_count
    FROM v_active_task_queue
    WHERE canonical_story_issue_number IS NOT NULL
    GROUP BY repo, canonical_story_issue_number
) active_tasks
  ON active_tasks.repo = ps.repo
 AND active_tasks.story_issue_number = ps.issue_number
LEFT JOIN v_story_decomposition_queue sdc
  ON sdc.repo = ps.repo
 AND sdc.story_issue_number = ps.issue_number
LEFT JOIN story_pull_request_link spl
  ON spl.repo = ps.repo
 AND spl.story_issue_number = ps.issue_number
WHERE ps.repo = %s
  AND ps.epic_issue_number = %s
ORDER BY ps.issue_number
"""

GET_EPIC_ACTIVE_TASKS_QUERY = """
SELECT
    wi.id AS work_id,
    wi.source_issue_number,
    wi.title,
    wi.status,
    wi.task_type,
    wi.blocking_mode,
    wi.blocked_reason,
    wi.decision_required,
    wi.attempt_count,
    wi.last_failure_reason,
    wi.next_eligible_at,
    wi.canonical_story_issue_number
FROM v_active_task_queue wi
JOIN program_story ps
  ON ps.repo = wi.repo
 AND ps.issue_number = wi.canonical_story_issue_number
WHERE wi.repo = %s
  AND ps.epic_issue_number = %s
ORDER BY wi.canonical_story_issue_number, wi.source_issue_number, wi.id
"""

GET_EPIC_DEPENDENCIES_QUERY = """
SELECT
    ped.depends_on_epic_issue_number AS epic_issue_number,
    dep.title,
    dep.execution_status,
    'depends_on' AS direction
FROM program_epic_dependency ped
JOIN program_epic dep
  ON dep.repo = ped.repo
 AND dep.issue_number = ped.depends_on_epic_issue_number
WHERE ped.repo = %s AND ped.epic_issue_number = %s
UNION ALL
SELECT
    ped.epic_issue_number AS epic_issue_number,
    dep.title,
    dep.execution_status,
    'required_by' AS direction
FROM program_epic_dependency ped
JOIN program_epic dep
  ON dep.repo = ped.repo
 AND dep.issue_number = ped.epic_issue_number
WHERE ped.repo = %s AND ped.depends_on_epic_issue_number = %s
ORDER BY direction, epic_issue_number
"""

GET_EPIC_EXECUTION_STATE_QUERY = """
SELECT
    status,
    completed_story_issue_numbers_json,
    blocked_story_issue_numbers_json,
    remaining_story_issue_numbers_json,
    verification_status,
    verification_reason_code,
    verification_summary,
    updated_at
FROM epic_execution_state
WHERE repo = %s AND epic_issue_number = %s
"""

GET_EPIC_RUNNING_JOBS_QUERY = """
SELECT id, job_kind, status, story_issue_number, worker_name, pid, command, log_path, started_at
FROM execution_job
WHERE repo = %s
  AND status = 'running'
  AND (
      story_issue_number IN (
          SELECT issue_number
          FROM program_story
          WHERE repo = %s AND epic_issue_number = %s
      )
      OR (job_kind = 'epic_decomposition' AND story_issue_number = %s)
  )
ORDER BY started_at DESC, id DESC
"""
