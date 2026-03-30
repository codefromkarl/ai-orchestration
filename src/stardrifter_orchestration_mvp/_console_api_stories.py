from __future__ import annotations

from typing import Any

import psycopg

from . import console_queries as queries
from ._console_api_internal import _fetch_all, _fetch_one, _normalize_row


def get_story_detail(
    connection: Any, *, repo: str, story_issue_number: int
) -> dict[str, Any]:
    from .console_api import ConsoleNotFoundError

    try:
        story = _fetch_one(
            connection,
            queries.GET_STORY_DETAIL_QUERY,
            (repo, story_issue_number),
        )
    except psycopg.errors.UndefinedTable as exc:
        if "story_verification_run" not in str(exc):
            raise
        if hasattr(connection, "rollback"):
            connection.rollback()
        story = _fetch_one(
            connection,
            queries.GET_STORY_DETAIL_QUERY_FALLBACK,
            (repo, story_issue_number),
        )

    if story is None:
        raise ConsoleNotFoundError(f"story #{story_issue_number} not found in {repo}")

    task_rows = _fetch_all(
        connection,
        queries.GET_STORY_TASKS_QUERY,
        (repo, story_issue_number),
    )

    drafts = _fetch_all(
        connection,
        queries.GET_STORY_DRAFTS_QUERY,
        (repo, story_issue_number),
    )

    dependencies = _fetch_all(
        connection,
        queries.GET_STORY_DEPENDENCIES_QUERY,
        (repo, story_issue_number, repo, story_issue_number),
    )

    running_jobs = _fetch_all(
        connection,
        queries.GET_STORY_RUNNING_JOBS_QUERY,
        (repo, story_issue_number),
    )

    decomposition_queue = _fetch_one(
        connection,
        queries.GET_STORY_DECOMPOSITION_QUEUE_QUERY,
        (repo, story_issue_number),
    )

    return {
        "repo": repo,
        "story": _normalize_row(story),
        "tasks": [_normalize_row(row) for row in task_rows],
        "task_drafts": [_normalize_row(row) for row in drafts],
        "dependencies": [_normalize_row(row) for row in dependencies],
        "jobs": [_normalize_row(row) for row in running_jobs],
        "decomposition_queue": _normalize_row(decomposition_queue or {}),
    }
