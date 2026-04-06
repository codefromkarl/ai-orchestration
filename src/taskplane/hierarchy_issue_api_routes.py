from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .hierarchy_api_support import close_connection, get_hierarchy_api_module, open_connection

router = APIRouter()


@router.get("/api/hierarchy")
def get_hierarchy(repo: str = Query(..., description="GitHub repo slug owner/repo")):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        issues = api._load_issues(conn, repo)
        work_map = api._load_work_items_by_issue(conn, repo)
    finally:
        close_connection(conn)

    by_number: dict[int, dict[str, Any]] = {
        row["issue_number"]: dict(row) for row in issues
    }
    stories_by_epic: dict[int, list[dict[str, Any]]] = {}
    tasks_by_story: dict[int, list[dict[str, Any]]] = {}
    claimed_stories: set[int] = set()
    claimed_tasks: set[int] = set()

    for issue in issues:
        parents = list(issue.get("explicit_parent_issue_numbers") or [])
        kind = issue.get("issue_kind")
        if kind == "story":
            for parent in parents:
                parent_issue = by_number.get(parent)
                if parent_issue is not None and parent_issue.get("issue_kind") == "epic":
                    stories_by_epic.setdefault(parent, []).append(dict(issue))
                    claimed_stories.add(issue["issue_number"])
                    break
        elif kind == "task":
            for parent in parents:
                parent_issue = by_number.get(parent)
                if (
                    parent_issue is not None
                    and parent_issue.get("issue_kind") == "story"
                ):
                    tasks_by_story.setdefault(parent, []).append(dict(issue))
                    claimed_tasks.add(issue["issue_number"])
                    break

    epics: list[dict[str, Any]] = []
    for issue in issues:
        if issue.get("issue_kind") != "epic":
            continue
        story_nodes = []
        for story in stories_by_epic.get(issue["issue_number"], []):
            task_nodes = [
                api._build_node(task, work_map, [])
                for task in tasks_by_story.get(story["issue_number"], [])
            ]
            story_nodes.append(api._build_node(story, work_map, task_nodes))
        epics.append(api._build_node(dict(issue), work_map, story_nodes))

    orphan_stories = [
        api._build_node(
            dict(issue),
            work_map,
            [
                api._build_node(task, work_map, [])
                for task in tasks_by_story.get(issue["issue_number"], [])
            ],
        )
        for issue in issues
        if issue.get("issue_kind") == "story"
        and issue["issue_number"] not in claimed_stories
    ]
    orphan_tasks = [
        api._build_node(dict(issue), work_map, [])
        for issue in issues
        if issue.get("issue_kind") == "task"
        and issue["issue_number"] not in claimed_tasks
    ]

    return JSONResponse(
        {
            "repo": repo,
            "epics": epics,
            "orphan_stories": orphan_stories,
            "orphan_tasks": orphan_tasks,
        }
    )


@router.get("/api/issue/{number}")
def get_issue(number: int, repo: str = Query(...)):
    conn = open_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT issue_number, title, body, url, github_state,
                       issue_kind, lane, complexity, status_label,
                       explicit_parent_issue_numbers,
                       explicit_story_dependency_issue_numbers,
                       explicit_task_dependency_issue_numbers
                FROM github_issue_normalized
                WHERE repo = %s AND issue_number = %s
                """,
                (repo, number),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"issue #{number} not found")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, wave, lane, blocked_reason, decision_required
                FROM work_item
                WHERE source_issue_number = %s AND repo = %s
                ORDER BY id LIMIT 1
                """,
                (number, repo),
            )
            work_item = cur.fetchone()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_issue_number AS num, relation_type, 'outgoing' AS dir
                FROM github_issue_relation
                WHERE repo = %s AND target_issue_number = %s
                UNION ALL
                SELECT target_issue_number, relation_type, 'incoming'
                FROM github_issue_relation
                WHERE repo = %s AND source_issue_number = %s
                """,
                (repo, number, repo, number),
            )
            relations = cur.fetchall()
    finally:
        close_connection(conn)

    return JSONResponse(
        {
            "issue_number": row["issue_number"],
            "title": row["title"],
            "issue_kind": row["issue_kind"],
            "github_state": row["github_state"],
            "body": (row["body"] or "")[:500],
            "url": row["url"],
            "lane": row["lane"],
            "complexity": row["complexity"],
            "status_label": row["status_label"],
            "parents": list(row["explicit_parent_issue_numbers"] or []),
            "work_item": dict(work_item) if work_item else None,
            "relations": [
                {
                    "number": relation["num"],
                    "type": relation["relation_type"],
                    "dir": relation["dir"],
                }
                for relation in relations
            ],
        }
    )
