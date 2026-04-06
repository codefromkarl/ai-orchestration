GET_STATUS_COUNTS_EXECUTION_QUERY = """
SELECT execution_status AS status, COUNT(*) AS count
FROM {table}
WHERE repo = %s
GROUP BY execution_status
ORDER BY execution_status
"""

GET_STATUS_COUNTS_STATUS_QUERY = """
SELECT status, COUNT(*) AS count
FROM {table}
WHERE repo = %s
GROUP BY status
ORDER BY status
"""

REQUIRE_REPO_QUERY = """
SELECT repo
FROM (
    SELECT repo FROM repo_registry
    UNION
    SELECT repo FROM program_epic
    UNION
    SELECT repo FROM program_story
    UNION
    SELECT repo FROM work_item WHERE repo IS NOT NULL
    UNION
    SELECT repo FROM github_issue_normalized
) repos
WHERE repo = %s
"""
