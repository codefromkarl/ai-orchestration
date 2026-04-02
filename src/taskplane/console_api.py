"""
Console read API module for taskplane.

This module provides read-only access to console data including:
- Repository listings
- Epic, Story, and Task details
- Execution job status
- Portfolio summaries

For SQL query definitions, see the console_queries package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from . import console_queries as queries
from ._console_api_internal import (
    _fetch_all,
    _fetch_one,
    get_agent_efficiency_stats,
    get_failed_notifications,
    _get_notification_query,
    _is_missing_epic_execution_state,
    list_agent_status,
    list_ai_decisions,
    _load_job_log_preview,
    list_notifications,
    _normalize_row,
    _normalize_value,
    _require_repo,
    _rollback_if_possible,
    list_portfolio_summary,
)
from ._console_api_epics import get_epic_detail, list_epic_rows, list_epic_story_tree
from ._console_api_repo_jobs import get_job_detail, get_repo_summary
from ._console_api_stories import get_story_detail
from ._console_api_tasks import get_task_detail, list_runtime_observability


@dataclass(frozen=True)
class ConsoleNotFoundError(Exception):
    """Exception raised when a requested console resource is not found."""

    message: str

    def __str__(self) -> str:
        return self.message


# =============================================================================
# Repository APIs
# =============================================================================


def list_repositories(connection: Any) -> dict[str, Any]:
    """List all repositories with their counts."""
    rows = _fetch_all(connection, queries.LIST_REPOSITORIES_QUERY)
    return {"repositories": [_normalize_row(row) for row in rows]}


def list_executor_routing_profiles(connection: Any) -> dict[str, Any]:
    rows = _fetch_all(connection, queries.LIST_EXECUTOR_ROUTING_PROFILES_QUERY)
    return {"profiles": [_normalize_row(row) for row in rows]}


def list_executor_selection_events(
    connection: Any,
    *,
    repo: str,
    limit: int = 100,
) -> dict[str, Any]:
    _require_repo(connection, repo)
    rows = _fetch_all(
        connection,
        queries.LIST_EXECUTOR_SELECTION_EVENTS_QUERY,
        (repo, limit),
    )
    return {"repo": repo, "events": [_normalize_row(row) for row in rows]}


# =============================================================================
# Job APIs
# =============================================================================


def list_running_jobs(connection: Any, *, repo: str) -> dict[str, Any]:
    """List all running jobs for a repository."""
    _require_repo(connection, repo)
    rows = _fetch_all(connection, queries.LIST_RUNNING_JOBS_QUERY, (repo,))
    return {"repo": repo, "jobs": [_normalize_row(row) for row in rows]}
