"""
Task scheduling and selection logic.

This module handles:
- Task candidate selection with dependency resolution
- Path conflict detection and estimation
- Task prioritization and ranking
"""

from __future__ import annotations

from typing import Any


def select_task_candidates(
    *,
    candidates: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    occupied_paths: list[str],
    max_parallel: int = 4,
) -> list[dict[str, Any]]:
    """
    Select task candidates with dependency and path conflict resolution.

    Args:
        candidates: List of task candidate rows
        dependencies: List of dependency relationships
        occupied_paths: List of already occupied file paths
        max_parallel: Maximum number of parallel tasks

    Returns:
        List of selected task rows
    """
    candidate_by_work_id = {row["work_id"]: row for row in candidates}
    dependency_rows_by_work_id: dict[str, list[dict[str, Any]]] = {}

    for row in dependencies:
        dependency_rows_by_work_id.setdefault(row["work_id"], []).append(row)

    def has_unmet_hard_dependency(
        work_id: str, visiting: set[str] | None = None
    ) -> bool:
        """Check if a task has unmet hard dependencies."""
        visiting = visiting or set()
        if work_id in visiting:
            return False
        visiting.add(work_id)

        for row in dependency_rows_by_work_id.get(work_id, []):
            blocking_mode = str(row.get("dependency_blocking_mode") or "hard")
            dependency_id = row["depends_on_work_id"]
            dependency_status = str(row.get("dependency_status") or "")

            if blocking_mode == "hard" and dependency_status != "done":
                return True

            if dependency_id in candidate_by_work_id and has_unmet_hard_dependency(
                dependency_id, visiting.copy()
            ):
                return True

        return False

    eligible_candidates = [
        row
        for row in candidates
        if row.get("status") == "ready"
        and not has_unmet_hard_dependency(row["work_id"])
    ]
    conflict_counts = estimate_conflict_counts(eligible_candidates)

    ordered = sorted(
        eligible_candidates,
        key=lambda row: (
            _task_type_rank(str(row.get("task_type") or "")),
            _blocking_mode_rank(str(row.get("blocking_mode") or "")),
            conflict_counts.get(row["work_id"], 0),
            int(row.get("source_issue_number") or 0),
        ),
    )

    # Group by Story for parallel execution
    stories_by_issue: dict[int, list[dict[str, Any]]] = {}
    for row in ordered:
        story_issue_number = row.get("canonical_story_issue_number")
        if story_issue_number is not None:
            stories_by_issue.setdefault(story_issue_number, []).append(row)

    # Select stories that can run in parallel
    selected: list[dict[str, Any]] = []
    selected_paths = list(occupied_paths)
    selected_story_issues: set[int] = set()

    for story_issue_number, story_tasks in stories_by_issue.items():
        if len(selected_story_issues) >= max_parallel:
            break

        # Check if this story's tasks conflict with already selected tasks
        story_paths: list[str] = []
        has_conflict = False

        for task in story_tasks:
            candidate_paths = scheduling_paths(task.get("planned_paths") or [])
            if _paths_conflict_with_any(candidate_paths, selected_paths):
                has_conflict = True
                break
            story_paths.extend(candidate_paths)

        if not has_conflict:
            selected_story_issues.add(story_issue_number)
            selected.extend(story_tasks)
            selected_paths.extend(story_paths)

    return selected


def estimate_conflict_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """
    Estimate the number of path conflicts for each task.

    Args:
        candidates: List of task candidate rows

    Returns:
        Dictionary mapping work_id to conflict count
    """
    scheduling_paths_by_work_id = {
        row["work_id"]: scheduling_paths(row.get("planned_paths") or [])
        for row in candidates
    }

    counts: dict[str, int] = {row["work_id"]: 0 for row in candidates}
    work_ids = [row["work_id"] for row in candidates]

    for index, left_work_id in enumerate(work_ids):
        for right_work_id in work_ids[index + 1 :]:
            if _paths_conflict_between(
                scheduling_paths_by_work_id[left_work_id],
                scheduling_paths_by_work_id[right_work_id],
            ):
                counts[left_work_id] += 1
                counts[right_work_id] += 1

    return counts


def scheduling_paths(raw_paths: list[str]) -> list[str]:
    """
    Normalize paths for scheduling purposes.

    - Strips whitespace and trailing slashes
    - Truncates at wildcard patterns
    - Filters empty paths

    Args:
        raw_paths: Raw path strings

    Returns:
        List of normalized paths
    """
    normalized: list[str] = []

    for raw_path in raw_paths:
        path = str(raw_path or "").strip().rstrip("/")
        if not path:
            continue
        if "*" in path:
            path = path.split("*", 1)[0].rstrip("/")
        normalized.append(path)

    return [path for path in normalized if path]


def paths_conflict_with_any(
    candidate_paths: list[str], occupied_paths: list[str]
) -> bool:
    """
    Check if any candidate path conflicts with occupied paths.

    Args:
        candidate_paths: Candidate paths to check
        occupied_paths: Already occupied paths

    Returns:
        True if any conflict exists
    """
    from ..queue import paths_conflict

    for candidate_path in candidate_paths:
        for occupied_path in occupied_paths:
            if paths_conflict(candidate_path, occupied_path):
                return True
    return False


def _paths_conflict_with_any(
    candidate_paths: list[str], occupied_paths: list[str]
) -> bool:
    """Internal alias for paths_conflict_with_any."""
    return paths_conflict_with_any(candidate_paths, occupied_paths)


def _paths_conflict_between(left_paths: list[str], right_paths: list[str]) -> bool:
    """Check if any path in left conflicts with any path in right."""
    from ..queue import paths_conflict

    for left_path in left_paths:
        for right_path in right_paths:
            if paths_conflict(left_path, right_path):
                return True
    return False


def _task_type_rank(task_type: str) -> int:
    """
    Get priority rank for task type.

    Lower values = higher priority
    """
    ranks = {
        "governance": 0,
        "core_path": 1,
        "cross_cutting": 2,
        "documentation": 3,
    }
    return ranks.get(task_type, 9)


def _blocking_mode_rank(blocking_mode: str) -> int:
    """
    Get priority rank for blocking mode.

    Lower values = higher priority
    """
    ranks = {
        "hard": 0,
        "soft": 1,
    }
    return ranks.get(blocking_mode, 9)


def group_stories_by_path_conflict(
    stories: list[dict[str, Any]],
    repository,
) -> list[list[dict[str, Any]]]:
    """
    Group stories by path conflicts.

    Stories in the same group can be executed in parallel without conflicts.

    Args:
        stories: List of story candidates
        repository: Repository instance for looking up story paths

    Returns:
        List of story groups, where stories within each group have no conflicts
    """
    if not stories:
        return []

    # Get paths for each story
    story_paths: dict[int, set[str]] = {}

    for story in stories:
        issue_number = story.get("issue_number")
        if issue_number is None:
            continue

        # Get paths from work items associated with this story
        work_item_ids = repository.list_story_work_item_ids(issue_number)
        paths: set[str] = set()

        for work_id in work_item_ids:
            work_item = repository.get_work_item(work_id)
            for path in work_item.planned_paths:
                paths.add(path.rstrip("/"))

        story_paths[issue_number] = paths

    # Greedy grouping
    groups: list[list[dict[str, Any]]] = []

    for story in stories:
        issue_number = story.get("issue_number")
        if issue_number is None:
            continue

        placed = False

        for group in groups:
            # Collect all paths in this group
            group_paths: set[str] = set()
            for group_story in group:
                group_issue = group_story.get("issue_number")
                if group_issue is not None:
                    group_paths.update(story_paths.get(group_issue, set()))

            # Check if this story can be added to the group
            if not _paths_conflict_between(
                list(story_paths.get(issue_number, set())),
                list(group_paths),
            ):
                group.append(story)
                placed = True
                break

        if not placed:
            groups.append([story])

    return groups
