from __future__ import annotations

from .models import ProgramStory
from .queue import paths_conflict


def select_story_batch(
    *,
    stories: list[ProgramStory],
    repository,
    max_batch_size: int = 1,
) -> list[ProgramStory]:
    if max_batch_size <= 0:
        return []

    story_dependencies = list(getattr(repository, "story_dependencies", []))
    selected: list[ProgramStory] = []
    selected_paths: list[str] = []

    for story in stories:
        if story.execution_status in {"done", "blocked"}:
            continue
        if _has_unmet_story_dependency(
            story_issue_number=story.issue_number,
            stories=stories,
            story_dependencies=story_dependencies,
        ):
            continue

        story_paths = _story_scheduling_paths(
            repository=repository,
            story_issue_number=story.issue_number,
        )
        # story_paths is None when story has no work items yet (still selectable)
        # story_paths is [] when work items exist but have no paths (not selectable)
        if story_paths is None:
            # No work items - allow selection without path conflict checking
            selected.append(story)
            if len(selected) >= max_batch_size:
                break
            continue
        if not story_paths:
            # Work items exist but no paths - skip this story
            continue
        if _paths_conflict_with_any(story_paths, selected_paths):
            continue
        selected.append(story)
        selected_paths.extend(story_paths)
        if len(selected) >= max_batch_size:
            break

    return selected


def _has_unmet_story_dependency(
    *,
    story_issue_number: int,
    stories: list[ProgramStory],
    story_dependencies: list[tuple[int, int]],
) -> bool:
    story_by_issue_number = {story.issue_number: story for story in stories}
    for candidate_story_issue_number, depends_on_story_issue_number in story_dependencies:
        if candidate_story_issue_number != story_issue_number:
            continue
        dependency = story_by_issue_number.get(depends_on_story_issue_number)
        if dependency is None:
            return True
        if dependency.execution_status != "done":
            return True
    return False


def _story_scheduling_paths(*, repository, story_issue_number: int) -> list[str] | None:
    work_item_ids = repository.list_story_work_item_ids(story_issue_number)
    if not work_item_ids:
        # No work items yet - return None to indicate "no paths, but still selectable"
        return None

    normalized: list[str] = []
    for work_item_id in work_item_ids:
        work_item = repository.get_work_item(work_item_id)
        work_item_paths = _normalize_paths(work_item.planned_paths)
        if not work_item_paths:
            return []
        normalized.extend(work_item_paths)
    return normalized


def _normalize_paths(raw_paths: tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for raw_path in raw_paths:
        path = str(raw_path or "").strip().rstrip("/")
        if not path:
            continue
        if "*" in path:
            path = path.split("*", 1)[0].rstrip("/")
        if path:
            normalized.append(path)
    return normalized


def _paths_conflict_with_any(
    candidate_paths: list[str], occupied_paths: list[str]
) -> bool:
    for candidate_path in candidate_paths:
        for occupied_path in occupied_paths:
            if paths_conflict(candidate_path, occupied_path):
                return True
    return False
