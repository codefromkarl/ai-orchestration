from __future__ import annotations

SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL = """
UPDATE program_epic
SET execution_status = %s,
    updated_at = NOW()
WHERE repo = %s AND issue_number = %s
"""

SET_PROGRAM_EPIC_EXECUTION_STATUS_WITH_PROPAGATION_SQL = """
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
"""

SET_PROGRAM_STORY_EXECUTION_STATUS_SQL = """
UPDATE program_story
SET execution_status = %s,
    updated_at = NOW()
WHERE repo = %s AND issue_number = %s
"""

SET_PROGRAM_STORY_EXECUTION_STATUS_WITH_PROPAGATION_SQL = """
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
      AND ps.program_status = 'approved'
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
"""


def build_epic_status_with_propagation_params(
    *,
    repo: str,
    issue_number: int,
    execution_status: str,
) -> tuple[object, ...]:
    return (
        repo,
        issue_number,
        repo,
        repo,
        execution_status,
        execution_status,
        execution_status,
        "backlog" if execution_status in {"backlog", "planned"} else execution_status,
        repo,
    )


def build_story_status_with_propagation_params(
    *,
    repo: str,
    issue_number: int,
    execution_status: str,
) -> tuple[object, ...]:
    return (
        repo,
        issue_number,
        issue_number,
        repo,
        repo,
        repo,
        execution_status,
        execution_status,
        repo,
    )
