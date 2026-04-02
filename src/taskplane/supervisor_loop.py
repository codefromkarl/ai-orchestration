"""
Backward compatibility layer for supervisor_loop.

This module now re-exports from scheduling_loop and related modules for backward compatibility.
New code should import from scheduling_loop directly.
"""

from __future__ import annotations

# Import from scheduling_loop which now re-exports these for compatibility
from .scheduling_loop import (
    run_epic_iteration,
    select_story_batch,
    run_supervisor_iteration,
    _load_running_jobs,
    _load_decomposition_candidates,
    _load_epic_decomposition_candidates,
    _load_task_candidates,
    _load_story_completion_candidates,
    _load_task_dependencies,
    _load_active_claim_paths,
    _derive_terminal_state_for_job,
    _pid_exists,
)

from .process_manager import (
    ManagedProcess,
    pid_exists,
    terminate_process_group,
    launch_managed_process,
    reconcile_finished_jobs,
)

from .repository import PostgresControlPlaneRepository


# Backward compatibility exception class
class _EpicIterationPreview(Exception):
    """Exception used for epic iteration preview."""

    def __init__(self, selected_story_issue_numbers: list[int]) -> None:
        super().__init__("epic iteration preview selected stories")
        self.selected_story_issue_numbers = selected_story_issue_numbers


__all__ = [
    "run_supervisor_iteration",
    "_load_running_jobs",
    "_load_decomposition_candidates",
    "_load_epic_decomposition_candidates",
    "_load_task_candidates",
    "_load_story_completion_candidates",
    "_load_task_dependencies",
    "_load_active_claim_paths",
    "_derive_terminal_state_for_job",
    "_pid_exists",
    "run_epic_iteration",
    "select_story_batch",
    "_EpicIterationPreview",
    "PostgresControlPlaneRepository",
    "ManagedProcess",
    "pid_exists",
    "terminate_process_group",
    "launch_managed_process",
    "reconcile_finished_jobs",
]
