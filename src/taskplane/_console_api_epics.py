from __future__ import annotations

from typing import Any

import psycopg

from . import console_queries as queries
from ._console_api_internal import (
    _fetch_all,
    _fetch_one,
    _is_missing_epic_execution_state,
    _normalize_row,
    _require_repo,
    _rollback_if_possible,
)


def list_epic_rows(connection: Any, *, repo: str) -> dict[str, Any]:
    _require_repo(connection, repo)

    try:
        rows = _fetch_all(
            connection,
            queries.LIST_EPIC_ROWS_QUERY,
            (repo, repo, repo, repo, repo, repo),
        )
    except psycopg.errors.UndefinedTable as exc:
        if not _is_missing_epic_execution_state(exc):
            raise
        _rollback_if_possible(connection)
        rows = _fetch_all(
            connection,
            queries.LIST_EPIC_ROWS_FALLBACK_QUERY,
            (repo, repo, repo, repo, repo, repo),
        )

    normalized_rows = []
    for row in rows:
        normalized = _normalize_row(row)
        normalized.pop("story_summaries", None)
        normalized_rows.append(normalized)

    return {"repo": repo, "rows": normalized_rows}


def list_epic_story_tree(connection: Any, *, repo: str) -> dict[str, Any]:
    _require_repo(connection, repo)
    rows = _fetch_all(
        connection,
        queries.LIST_EPIC_STORY_TREE_QUERY,
        (repo, repo, repo, repo, repo),
    )
    return {"repo": repo, "rows": [_normalize_row(row) for row in rows]}


def get_epic_detail(
    connection: Any, *, repo: str, epic_issue_number: int
) -> dict[str, Any]:
    from .console_api import ConsoleNotFoundError

    epic = _fetch_one(
        connection,
        queries.GET_EPIC_DETAIL_QUERY,
        (repo, epic_issue_number),
    )

    if epic is None:
        raise ConsoleNotFoundError(f"epic #{epic_issue_number} not found in {repo}")

    stories = _fetch_all(
        connection,
        queries.GET_EPIC_STORIES_QUERY,
        (repo, epic_issue_number),
    )

    active_tasks = _fetch_all(
        connection,
        queries.GET_EPIC_ACTIVE_TASKS_QUERY,
        (repo, epic_issue_number),
    )

    epic_dependencies = _fetch_all(
        connection,
        queries.GET_EPIC_DEPENDENCIES_QUERY,
        (repo, epic_issue_number, repo, epic_issue_number),
    )

    try:
        execution_state = _fetch_one(
            connection,
            queries.GET_EPIC_EXECUTION_STATE_QUERY,
            (repo, epic_issue_number),
        )
    except psycopg.errors.UndefinedTable as exc:
        if not _is_missing_epic_execution_state(exc):
            raise
        _rollback_if_possible(connection)
        execution_state = None

    running_jobs = _fetch_all(
        connection,
        queries.GET_EPIC_RUNNING_JOBS_QUERY,
        (repo, repo, epic_issue_number, epic_issue_number),
    )

    return {
        "repo": repo,
        "epic": _normalize_row(epic),
        "stories": [_normalize_row(row) for row in stories],
        "active_tasks": [_normalize_row(row) for row in active_tasks],
        "dependencies": [_normalize_row(row) for row in epic_dependencies],
        "execution_state": _normalize_row(execution_state or {}),
        "running_jobs": [_normalize_row(row) for row in running_jobs],
    }
