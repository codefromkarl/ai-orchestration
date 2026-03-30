"""Shared priority snapshot logic for CLI and API consumption."""

from __future__ import annotations

from typing import Any


def load_priority_snapshot(
    *,
    connection: Any,
    repo: str,
) -> dict[str, list[dict[str, Any]]]:
    """Load a governance priority snapshot from the control plane.

    Returns structured data suitable for both CLI printing and JSON API responses.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wi.source_issue_number,
                wi.title,
                wi.task_type,
                wi.blocking_mode,
                wi.status,
                wi.canonical_story_issue_number AS story_issue_number,
                s.title AS story_title,
                e.issue_number AS epic_issue_number,
                e.title AS epic_title
            FROM v_active_task_queue wi
            JOIN program_story s
              ON s.repo = wi.repo
             AND s.issue_number = wi.canonical_story_issue_number
            JOIN program_epic e
              ON e.repo = s.repo
             AND e.issue_number = s.epic_issue_number
            WHERE wi.repo = %s
              AND wi.status <> 'done'
            ORDER BY
                CASE wi.task_type
                    WHEN 'governance' THEN 0
                    WHEN 'core_path' THEN 1
                    WHEN 'cross_cutting' THEN 2
                    ELSE 3
                END,
                CASE wi.blocking_mode
                    WHEN 'hard' THEN 0
                    ELSE 1
                END,
                wi.source_issue_number
            """,
            (repo,),
        )
        active_tasks = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                repo,
                epic_issue_number,
                epic_title,
                story_issue_number,
                story_title,
                execution_status,
                story_task_count
            FROM v_story_decomposition_queue
            WHERE repo = %s
            ORDER BY story_issue_number
            """,
            (repo,),
        )
        decomposition_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                repo,
                epic_issue_number,
                epic_title,
                execution_status,
                epic_story_count
            FROM v_epic_decomposition_queue
            WHERE repo = %s
            ORDER BY epic_issue_number
            """,
            (repo,),
        )
        epic_decomposition_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                tree.story_issue_number,
                tree.story_title,
                tree.epic_issue_number,
                tree.epic_title,
                tree.story_execution_status
            FROM v_program_tree tree
            WHERE tree.repo = %s
              AND tree.epic_execution_status = 'active'
              AND tree.story_execution_status = 'needs_story_refinement'
            ORDER BY tree.story_issue_number
            """,
            (repo,),
        )
        refinement_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                e.issue_number,
                e.title,
                e.execution_status,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status = 'done'
                ) AS done_dependency_count,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status = 'active'
                ) AS active_dependency_count,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status NOT IN ('active', 'done')
                ) AS blocked_dependency_count,
                ARRAY_REMOVE(
                    ARRAY_AGG(
                        CASE
                            WHEN dep.execution_status = 'active'
                            THEN format('#%%s(active)', dep.issue_number)
                        END
                        ORDER BY dep.issue_number
                    ),
                    NULL
                ) AS active_dependencies,
                ARRAY_REMOVE(
                    ARRAY_AGG(
                        CASE
                            WHEN dep.execution_status NOT IN ('active', 'done')
                            THEN format('#%%s(%%s)', dep.issue_number, dep.execution_status::text)
                        END
                        ORDER BY dep.issue_number
                    ),
                    NULL
                ) AS blocked_dependencies
            FROM program_epic e
            LEFT JOIN program_epic_dependency ped
              ON ped.repo = e.repo
             AND ped.epic_issue_number = e.issue_number
            LEFT JOIN program_epic dep
              ON dep.repo = ped.repo
             AND dep.issue_number = ped.depends_on_epic_issue_number
            WHERE e.repo = %s
              AND e.program_status = 'approved'
              AND e.execution_status = 'gated'
            GROUP BY e.issue_number, e.title, e.execution_status
            ORDER BY
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status NOT IN ('active', 'done')
                ),
                e.issue_number
            """,
            (repo,),
        )
        gated_epics = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT issue_number, title, execution_status
            FROM program_epic
            WHERE repo = %s
              AND program_status = 'approved'
              AND execution_status = 'planned'
            ORDER BY issue_number
            """,
            (repo,),
        )
        planned_epics = list(cursor.fetchall())

    return {
        "active_tasks": active_tasks,
        "decomposition_queue": decomposition_queue,
        "epic_decomposition_queue": epic_decomposition_queue,
        "refinement_queue": refinement_queue,
        "gated_epics": gated_epics,
        "planned_epics": planned_epics,
    }


def build_priority_score(task: dict[str, Any], *, index: int) -> float:
    """Calculate a normalized priority score (0-1) for a task.

    Higher score = higher priority.
    """
    score = 1.0

    task_type_scores = {
        "governance": 1.0,
        "core_path": 0.85,
        "cross_cutting": 0.7,
    }
    score *= task_type_scores.get(str(task.get("task_type", "")).lower(), 0.5)

    if str(task.get("blocking_mode", "")).lower() == "hard":
        score *= 1.0
    else:
        score *= 0.7

    rank_factor = max(0.1, 1.0 - (index * 0.05))
    score *= rank_factor

    return round(min(1.0, max(0.0, score)), 3)


def build_api_response(
    *,
    repo: str,
    snapshot: dict[str, list[dict[str, Any]]],
    generated_at: str,
) -> dict[str, Any]:
    """Convert a raw priority snapshot into a structured API response."""
    tasks = []
    for i, task in enumerate(snapshot.get("active_tasks", [])):
        tasks.append(
            {
                "source_issue_number": task["source_issue_number"],
                "title": task["title"],
                "task_type": task["task_type"],
                "blocking_mode": task["blocking_mode"],
                "status": task["status"],
                "story_issue_number": task["story_issue_number"],
                "story_title": task["story_title"],
                "epic_issue_number": task["epic_issue_number"],
                "epic_title": task["epic_title"],
                "priority_score": build_priority_score(task, index=i),
                "kind": "active_task",
            }
        )

    for i, item in enumerate(snapshot.get("decomposition_queue", [])):
        tasks.append(
            {
                "story_issue_number": item["story_issue_number"],
                "story_title": item["story_title"],
                "epic_issue_number": item["epic_issue_number"],
                "epic_title": item["epic_title"],
                "execution_status": item["execution_status"],
                "task_count": item["story_task_count"],
                "priority_score": build_priority_score(
                    {"task_type": "governance", "blocking_mode": "hard"},
                    index=len(tasks) + i,
                ),
                "kind": "story_decomposition",
            }
        )

    for i, item in enumerate(snapshot.get("epic_decomposition_queue", [])):
        tasks.append(
            {
                "epic_issue_number": item["epic_issue_number"],
                "epic_title": item["epic_title"],
                "execution_status": item["execution_status"],
                "story_count": item["epic_story_count"],
                "priority_score": build_priority_score(
                    {"task_type": "governance", "blocking_mode": "hard"},
                    index=len(tasks) + i,
                ),
                "kind": "epic_decomposition",
            }
        )

    return {
        "repo": repo,
        "generated_at": generated_at,
        "task_count": len(tasks),
        "tasks": tasks,
    }
