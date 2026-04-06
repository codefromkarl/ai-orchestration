from __future__ import annotations

from importlib import import_module
from typing import Any

from fastapi import HTTPException


def get_hierarchy_api_module() -> Any:
    return import_module("taskplane.hierarchy_api")


def open_connection() -> Any:
    api = get_hierarchy_api_module()
    try:
        return api._get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def close_connection(connection: Any) -> None:
    api = get_hierarchy_api_module()
    api._close_connection(connection)


def close_repository_connection(repository: Any) -> None:
    connection = getattr(repository, "_connection", None)
    if connection is not None:
        close_connection(connection)


def map_console_not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def map_console_action_configuration(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


def map_console_action_conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def load_issues(connection: Any, repo: str) -> list[dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT issue_number, title, body, url, github_state,
                   issue_kind, lane, complexity, status_label,
                   explicit_parent_issue_numbers,
                   explicit_story_dependency_issue_numbers,
                   explicit_task_dependency_issue_numbers
            FROM github_issue_normalized
            WHERE repo = %s
            ORDER BY issue_number
            """,
            (repo,),
        )
        return cur.fetchall()


def load_work_items_by_issue(connection: Any, repo: str) -> dict[int, dict[str, Any]]:
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT source_issue_number, id, status, wave, lane,
                   blocked_reason, decision_required
            FROM work_item
            WHERE source_issue_number IS NOT NULL
              AND repo = %s
            """,
            (repo,),
        )
        rows = cur.fetchall()
    return {row["source_issue_number"]: dict(row) for row in rows}


def build_issue_node(
    issue: dict[str, Any],
    work_map: dict[int, dict[str, Any]],
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    issue_number = issue["issue_number"]
    work_item = work_map.get(issue_number)
    return {
        "issue_number": issue_number,
        "title": issue["title"],
        "issue_kind": issue["issue_kind"] or "unknown",
        "github_state": issue["github_state"],
        "status_label": issue["status_label"],
        "url": issue["url"],
        "lane": issue["lane"],
        "complexity": issue["complexity"],
        "work_status": work_item["status"] if work_item else None,
        "blocked_reason": work_item["blocked_reason"] if work_item else None,
        "decision_required": work_item["decision_required"] if work_item else False,
        "children": children,
    }
