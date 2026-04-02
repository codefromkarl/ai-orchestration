from __future__ import annotations

from typing import Any


DEFAULT_THRESHOLDS: dict[str, int] = {
    "epic_story_count": 10,
    "story_task_count": 6,
    "decomposing_hours": 24,
}


def load_split_candidates(
    *,
    connection: Any,
    repo: str,
    thresholds: dict[str, int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    t = thresholds or DEFAULT_THRESHOLDS

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                e.issue_number AS epic_issue_number,
                e.title AS epic_title,
                e.execution_status,
                COUNT(s.issue_number) AS story_count
            FROM program_epic e
            LEFT JOIN program_story s
              ON s.repo = e.repo
             AND s.epic_issue_number = e.issue_number
            WHERE e.repo = %s
              AND e.execution_status NOT IN ('done', 'backlog')
            GROUP BY e.issue_number, e.title, e.execution_status
            HAVING COUNT(s.issue_number) > %s
            ORDER BY COUNT(s.issue_number) DESC
            """,
            (repo, t["epic_story_count"]),
        )
        oversized_epics = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                s.issue_number AS story_issue_number,
                s.title AS story_title,
                s.epic_issue_number,
                s.execution_status,
                COUNT(wi.id) AS task_count
            FROM program_story s
            LEFT JOIN work_item wi
              ON wi.repo = s.repo
             AND wi.canonical_story_issue_number = s.issue_number
            WHERE s.repo = %s
              AND s.execution_status NOT IN ('done')
            GROUP BY s.issue_number, s.title, s.epic_issue_number, s.execution_status
            HAVING COUNT(wi.id) > %s
            ORDER BY COUNT(wi.id) DESC
            """,
            (repo, t["story_task_count"]),
        )
        oversized_stories = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                s.issue_number AS story_issue_number,
                s.title AS story_title,
                s.epic_issue_number,
                s.execution_status
            FROM program_story s
            WHERE s.repo = %s
              AND s.execution_status = 'decomposing'
              AND s.updated_at < NOW() - INTERVAL '%s hours'
            ORDER BY s.updated_at
            """,
            (repo, t["decomposing_hours"]),
        )
        stuck_stories = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                e.issue_number AS epic_issue_number,
                e.title AS epic_title,
                e.execution_status
            FROM program_epic e
            WHERE e.repo = %s
              AND e.execution_status = 'decomposing'
              AND NOT EXISTS (
                SELECT 1 FROM program_story s
                WHERE s.repo = e.repo
                  AND s.epic_issue_number = e.issue_number
              )
            ORDER BY e.issue_number
            """,
            (repo,),
        )
        empty_epics = [dict(r) for r in cursor.fetchall()]

    return {
        "oversized_epics": oversized_epics,
        "oversized_stories": oversized_stories,
        "stuck_stories": stuck_stories,
        "empty_epics": empty_epics,
    }


def evaluate_auto_splits(
    *,
    connection: Any,
    repo: str,
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    t = thresholds or DEFAULT_THRESHOLDS
    candidates = load_split_candidates(connection=connection, repo=repo, thresholds=t)

    triggered = []
    evaluated = 0

    for epic in candidates["oversized_epics"]:
        evaluated += 1
        triggered.append(
            {
                "type": "epic_re_split",
                "epic_issue_number": epic["epic_issue_number"],
                "epic_title": epic["epic_title"],
                "reason": "story_count_exceeded",
                "current": epic["story_count"],
                "threshold": t["epic_story_count"],
            }
        )

    for story in candidates["oversized_stories"]:
        evaluated += 1
        triggered.append(
            {
                "type": "story_re_split",
                "story_issue_number": story["story_issue_number"],
                "story_title": story["story_title"],
                "epic_issue_number": story["epic_issue_number"],
                "reason": "task_count_exceeded",
                "current": story["task_count"],
                "threshold": t["story_task_count"],
            }
        )

    for story in candidates["stuck_stories"]:
        evaluated += 1
        triggered.append(
            {
                "type": "story_stuck",
                "story_issue_number": story["story_issue_number"],
                "story_title": story["story_title"],
                "epic_issue_number": story["epic_issue_number"],
                "reason": "decomposing_timeout",
                "threshold_hours": t["decomposing_hours"],
            }
        )

    for epic in candidates["empty_epics"]:
        evaluated += 1
        triggered.append(
            {
                "type": "epic_empty_after_decomposition",
                "epic_issue_number": epic["epic_issue_number"],
                "epic_title": epic["epic_title"],
                "reason": "no_stories_after_decomposition",
            }
        )

    return {
        "repo": repo,
        "evaluated": evaluated,
        "triggered": len(triggered),
        "thresholds": t,
        "actions": triggered,
    }
