from __future__ import annotations

from .models import WorkDependency, WorkItem


def derive_ready_work_ids(
    work_items: list[WorkItem],
    dependencies: list[WorkDependency],
    *,
    story_dependencies: list[tuple[int, int]] | None = None,
) -> set[str]:
    item_by_id = {item.id: item for item in work_items}
    status_by_id = {item.id: item.status for item in work_items}
    dependency_map: dict[str, set[str]] = {}
    for dependency in dependencies:
        dependency_map.setdefault(dependency.work_id, set()).add(
            dependency.depends_on_work_id
        )
    dependent_story_numbers_by_story: dict[int, set[int]] = {}
    if story_dependencies is None:
        story_dependencies = []
    for story_issue_number, depends_on_story_issue_number in story_dependencies:
        dependent_story_numbers_by_story.setdefault(story_issue_number, set()).add(
            depends_on_story_issue_number
        )
    non_done_count_by_story: dict[int, int] = {}
    present_story_numbers: set[int] = set()
    for item in work_items:
        item_story_numbers = _story_numbers_for_planning(item)
        for story_issue_number in item_story_numbers:
            present_story_numbers.add(story_issue_number)
            if item.status != "done":
                non_done_count_by_story[story_issue_number] = (
                    non_done_count_by_story.get(story_issue_number, 0) + 1
                )

    ready_ids: set[str] = set()
    for item in work_items:
        if item.status not in {"pending", "ready"}:
            continue
        blockers = dependency_map.get(item.id, set())
        hard_blockers = {
            blocker_id
            for blocker_id in blockers
            if _is_hard_blocker(item_by_id.get(blocker_id))
        }
        if all(status_by_id.get(blocker_id) == "done" for blocker_id in hard_blockers):
            own_story_numbers = set(_story_numbers_for_planning(item))
            story_blockers = {
                depends_on_story_issue_number
                for story_issue_number in own_story_numbers
                for depends_on_story_issue_number in dependent_story_numbers_by_story.get(
                    story_issue_number, set()
                )
                if depends_on_story_issue_number not in own_story_numbers
            }
            if all(
                story_issue_number in present_story_numbers
                and non_done_count_by_story.get(story_issue_number, 0) == 0
                for story_issue_number in story_blockers
            ):
                ready_ids.add(item.id)

    return ready_ids


def _canonical_story_issue_number(item: WorkItem) -> int | None:
    if item.canonical_story_issue_number is not None:
        return item.canonical_story_issue_number
    if item.story_issue_numbers:
        return item.story_issue_numbers[0]
    return None


def _story_numbers_for_planning(item: WorkItem) -> tuple[int, ...]:
    if item.story_issue_numbers:
        return item.story_issue_numbers
    canonical_story_issue_number = _canonical_story_issue_number(item)
    if canonical_story_issue_number is None:
        return ()
    return (canonical_story_issue_number,)


def _is_hard_blocker(item: WorkItem | None) -> bool:
    if item is None:
        return True
    return item.blocking_mode == "hard"
