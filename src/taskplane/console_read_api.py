"""
Backward compatibility layer for console_read_api.

This module now re-exports from console_api for backward compatibility.
New code should import from console_api directly.
"""

from __future__ import annotations

from .console_api import (
    ConsoleNotFoundError,
    list_executor_routing_profiles,
    list_executor_selection_events,
    list_repositories,
    get_repo_summary,
    list_running_jobs,
    list_epic_rows,
    list_epic_story_tree,
    get_epic_detail,
    get_story_detail,
    get_task_detail,
    list_runtime_observability,
    get_job_detail,
    list_portfolio_summary,
    list_ai_decisions,
    list_notifications,
    list_agent_status,
    get_failed_notifications,
    get_agent_efficiency_stats,
)

__all__ = [
    "ConsoleNotFoundError",
    "list_executor_routing_profiles",
    "list_executor_selection_events",
    "list_repositories",
    "get_repo_summary",
    "list_running_jobs",
    "list_epic_rows",
    "list_epic_story_tree",
    "get_epic_detail",
    "get_story_detail",
    "get_task_detail",
    "list_runtime_observability",
    "get_job_detail",
    "list_portfolio_summary",
    "list_ai_decisions",
    "list_notifications",
    "list_agent_status",
    "get_failed_notifications",
    "get_agent_efficiency_stats",
]
