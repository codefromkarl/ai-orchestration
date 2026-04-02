"""
Scheduler modules for story and task selection logic.

This package contains the scheduling algorithms for:
- Story batch selection and prioritization
- Task candidate selection with dependency resolution
- Path conflict detection and resolution
"""

# Export story scheduler items
# Export task scheduler items

__all__ = [
    # Story scheduler
    "select_story_batch",
    "select_story_candidates_via_epic_iteration",
    "select_story_completion_candidates",
    # Task scheduler
    "select_task_candidates",
    "estimate_conflict_counts",
    "paths_conflict_with_any",
    "scheduling_paths",
    "group_stories_by_path_conflict",
]

# Import after __all__ to avoid circular dependency issues
from .story_scheduler import (
    select_story_batch,
    select_story_candidates_via_epic_iteration,
    select_story_completion_candidates,
)
from .task_scheduler import (
    select_task_candidates,
    estimate_conflict_counts,
    paths_conflict_with_any,
    scheduling_paths,
    group_stories_by_path_conflict,
)
