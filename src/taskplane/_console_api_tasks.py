from __future__ import annotations

from typing import Any

from . import console_queries as queries
from ._console_api_internal import (
    _build_retry_context,
    _fetch_all,
    _fetch_one,
    _normalize_row,
)
from ._console_api_repo_jobs import get_repo_snapshot_health


def get_task_detail(connection: Any, *, repo: str, work_id: str) -> dict[str, Any]:
    from .console_api import ConsoleNotFoundError

    task = _fetch_one(
        connection,
        queries.GET_TASK_DETAIL_QUERY,
        (repo, work_id),
    )

    if task is None:
        raise ConsoleNotFoundError(f"task {work_id} not found in {repo}")

    recent_runs = _fetch_all(
        connection,
        queries.GET_TASK_RECENT_RUNS_QUERY,
        (work_id,),
    )

    claim = _fetch_one(
        connection,
        queries.GET_TASK_CLAIM_QUERY,
        (work_id,),
    )

    approval_events = _fetch_all(
        connection,
        queries.GET_TASK_APPROVAL_EVENTS_QUERY,
        (work_id,),
    )

    commit_link = _fetch_one(
        connection,
        queries.GET_TASK_COMMIT_LINK_QUERY,
        (work_id,),
    )

    pull_requests = _fetch_all(
        connection,
        queries.GET_TASK_PULL_REQUESTS_QUERY,
        (work_id,),
    )

    jobs = _fetch_all(
        connection,
        queries.GET_TASK_JOBS_QUERY,
        (repo, work_id),
    )
    sessions = _fetch_all(
        connection,
        queries.GET_TASK_SESSIONS_QUERY,
        (work_id,),
    )
    artifacts = _fetch_all(
        connection,
        queries.GET_TASK_ARTIFACTS_QUERY,
        (work_id,),
    )

    retry_context = _build_retry_context(task=task, recent_runs=recent_runs)

    return {
        "repo": repo,
        "task": _normalize_row(task),
        "snapshot_state": _normalize_row(get_repo_snapshot_health(repo=repo)),
        "retry_context": _normalize_row(retry_context),
        "recent_runs": [_normalize_row(row) for row in recent_runs],
        "active_claim": _normalize_row(claim or {}),
        "approval_events": [_normalize_row(row) for row in approval_events],
        "commit_link": _normalize_row(commit_link or {}),
        "pull_requests": [_normalize_row(row) for row in pull_requests],
        "jobs": [_normalize_row(row) for row in jobs],
        "sessions": [_normalize_row(row) for row in sessions],
        "artifacts": [_normalize_row(row) for row in artifacts],
    }


def list_runtime_observability(connection: Any, *, repo: str) -> dict[str, Any]:
    from .console_api import ConsoleNotFoundError

    task = _fetch_one(
        connection,
        queries.REQUIRE_REPO_QUERY,
        (repo,),
    )
    if task is None:
        raise ConsoleNotFoundError(f"repo {repo} not found")

    rows = _fetch_all(
        connection,
        queries.LIST_RUNTIME_OBSERVABILITY_QUERY,
        (repo,),
    )
    return {
        "repo": repo,
        "items": [_normalize_row(row) for row in rows],
    }
