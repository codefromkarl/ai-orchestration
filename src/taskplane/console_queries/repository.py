LIST_REPOSITORIES_QUERY = """
WITH repos AS (
    SELECT repo FROM repo_registry
    UNION
    SELECT repo FROM program_epic
    UNION
    SELECT repo FROM program_story
    UNION
    SELECT repo FROM work_item WHERE repo IS NOT NULL
    UNION
    SELECT repo FROM github_issue_normalized
),
epic_counts AS (
    SELECT repo, COUNT(*) AS epic_count
    FROM program_epic
    GROUP BY repo
),
story_counts AS (
    SELECT repo, COUNT(*) AS story_count
    FROM program_story
    GROUP BY repo
),
task_counts AS (
    SELECT repo, COUNT(*) AS task_count
    FROM work_item
    WHERE repo IS NOT NULL
    GROUP BY repo
),
active_task_counts AS (
    SELECT repo, COUNT(*) AS active_task_count
    FROM v_active_task_queue
    GROUP BY repo
)
SELECT
    repos.repo,
    COALESCE(epic_counts.epic_count, 0) AS epic_count,
    COALESCE(story_counts.story_count, 0) AS story_count,
    COALESCE(task_counts.task_count, 0) AS task_count,
    COALESCE(active_task_counts.active_task_count, 0) AS active_task_count
FROM repos
LEFT JOIN epic_counts ON epic_counts.repo = repos.repo
LEFT JOIN story_counts ON story_counts.repo = repos.repo
LEFT JOIN task_counts ON task_counts.repo = repos.repo
LEFT JOIN active_task_counts ON active_task_counts.repo = repos.repo
ORDER BY repos.repo
"""

GET_REPO_SUMMARY_QUERY = """
WITH running_jobs AS (
    SELECT repo, COUNT(*) AS running_job_count
    FROM execution_job
    WHERE status = 'running'
    GROUP BY repo
),
queued_story_decomposition AS (
    SELECT repo, COUNT(*) AS queued_story_decomposition_count
    FROM v_story_decomposition_queue
    GROUP BY repo
),
queued_epic_decomposition AS (
    SELECT repo, COUNT(*) AS queued_epic_decomposition_count
    FROM v_epic_decomposition_queue
    GROUP BY repo
)
SELECT
    %s AS repo,
    (SELECT COUNT(*) FROM program_epic WHERE repo = %s) AS epic_count,
    (SELECT COUNT(*) FROM program_story WHERE repo = %s) AS story_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s) AS task_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s AND status = 'ready') AS ready_task_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s AND status = 'in_progress') AS in_progress_task_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s AND status = 'blocked') AS blocked_task_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s AND status = 'done') AS done_task_count,
    (SELECT COUNT(*) FROM work_item WHERE repo = %s AND decision_required IS TRUE) AS decision_required_task_count,
    COALESCE((SELECT running_job_count FROM running_jobs WHERE repo = %s), 0) AS running_job_count,
    COALESCE((SELECT queued_story_decomposition_count FROM queued_story_decomposition WHERE repo = %s), 0) AS queued_story_decomposition_count,
    COALESCE((SELECT queued_epic_decomposition_count FROM queued_epic_decomposition WHERE repo = %s), 0) AS queued_epic_decomposition_count,
    (SELECT MAX(updated_at) FROM work_item WHERE repo = %s) AS latest_task_update_at,
    (SELECT MAX(updated_at) FROM program_epic WHERE repo = %s) AS latest_epic_update_at,
    (SELECT MAX(updated_at) FROM program_story WHERE repo = %s) AS latest_story_update_at
"""

GET_REPO_REGISTRY_ENTRY_QUERY = """
SELECT
    repo,
    workdir,
    log_dir,
    created_at,
    updated_at
FROM repo_registry
WHERE repo = %s
"""

LIST_EXECUTOR_ROUTING_PROFILES_QUERY = """
SELECT
    tem.id,
    tem.task_type,
    tem.priority,
    tem.preferred_executor,
    preferred.executor_type AS preferred_executor_type,
    tem.fallback_executor,
    fallback.executor_type AS fallback_executor_type,
    tem.conditions,
    tem.created_at,
    tem.updated_at
FROM task_executor_mapping tem
LEFT JOIN executor_registry preferred
  ON preferred.executor_name = tem.preferred_executor
LEFT JOIN executor_registry fallback
  ON fallback.executor_name = tem.fallback_executor
ORDER BY tem.task_type ASC, tem.priority DESC, tem.id ASC
"""

LIST_EXECUTOR_SELECTION_EVENTS_QUERY = """
SELECT
    el.id,
    el.work_id,
    wi.source_issue_number,
    wi.title AS work_title,
    el.actor,
    el.detail->>'executor_name' AS executor_name,
    el.detail->>'executor_type' AS executor_type,
    el.detail->>'task_type' AS task_type,
    el.detail->>'lane' AS lane,
    el.detail->>'wave' AS wave,
    el.created_at
FROM event_log el
LEFT JOIN work_item wi
  ON wi.id = el.work_id
WHERE el.event_type = 'executor_selected'
  AND wi.repo = %s
ORDER BY el.created_at DESC, el.id DESC
LIMIT %s
"""
