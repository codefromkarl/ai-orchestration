"""
Story scheduling and batch selection logic.

This module handles:
- Story batch selection based on dependencies and capacity
- Epic iteration story preview and selection
- Story completion candidate selection
"""

from __future__ import annotations

from typing import Any

from ..epic_scheduler import select_story_batch
from ..models import ProgramStory
from ..repository import ControlPlaneRepository


def select_story_candidates_via_epic_iteration(
    *,
    connection: Any,
    repo: str,
    repository: ControlPlaneRepository,
    running_story_issue_numbers: set[int],
    available_capacity: int,
    epic_story_batch_size: int = 1,
    epic_iteration_runner=None,
) -> tuple[list[int], dict[int, int]]:
    """
    Select story candidates via epic iteration.

    Args:
        connection: Database connection
        repo: Repository name
        repository: Repository instance
        running_story_issue_numbers: Set of already running story issue numbers
        available_capacity: Available capacity for new stories
        epic_story_batch_size: Batch size for epic iteration
        epic_iteration_runner: Optional custom epic iteration runner

    Returns:
        Tuple of (selected_story_issue_numbers, epic_issue_by_story_issue_number)
    """
    if available_capacity <= 0:
        return [], {}

    from ..epic_runner import run_epic_iteration

    effective_runner = epic_iteration_runner or run_epic_iteration

    selected_story_issue_numbers: list[int] = []
    epic_issue_by_story_issue_number: dict[int, int] = {}
    selected_story_issue_number_set: set[int] = set()

    for row in _load_epic_iteration_candidates(connection, repo):
        if len(selected_story_issue_numbers) >= available_capacity:
            break

        epic_issue_number = row.get("epic_issue_number")
        if epic_issue_number is None:
            continue

        story_issue_numbers = _preview_epic_iteration_story_selection(
            repo=repo,
            epic_issue_number=int(epic_issue_number),
            repository=repository,
            max_parallel_stories=min(
                max(1, epic_story_batch_size),
                available_capacity - len(selected_story_issue_numbers),
            ),
            epic_iteration_runner=effective_runner,
        )

        for story_issue_number in story_issue_numbers:
            if len(selected_story_issue_numbers) >= available_capacity:
                break
            if story_issue_number in running_story_issue_numbers:
                continue
            if story_issue_number in selected_story_issue_number_set:
                continue

            selected_story_issue_numbers.append(story_issue_number)
            selected_story_issue_number_set.add(story_issue_number)
            epic_issue_by_story_issue_number[story_issue_number] = int(
                epic_issue_number
            )
            running_story_issue_numbers.add(story_issue_number)

    return selected_story_issue_numbers, epic_issue_by_story_issue_number


def _load_epic_iteration_candidates(connection: Any, repo: str) -> list[dict[str, Any]]:
    """Load epic iteration candidates from database."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT issue_number AS epic_issue_number
            FROM program_epic
            WHERE repo = %s
              AND execution_status NOT IN ('done', 'gated')
            ORDER BY issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _preview_epic_iteration_story_selection(
    *,
    repo: str,
    epic_issue_number: int,
    repository: ControlPlaneRepository,
    max_parallel_stories: int,
    epic_iteration_runner=None,
) -> list[int]:
    """
    Preview story selection for epic iteration without executing.

    Uses a preview repository and exception-based early termination
    to capture the selected stories.
    """
    from ..epic_runner import run_epic_iteration

    effective_runner = epic_iteration_runner or run_epic_iteration
    captured_story_issue_numbers: list[int] = []

    class PreviewRepository:
        """Read-only preview repository for story selection."""

        story_dependencies = getattr(repository, "story_dependencies", [])

        def list_program_stories_for_epic(
            self, *, repo: str, epic_issue_number: int
        ) -> list[ProgramStory]:
            return repository.list_program_stories_for_epic(
                repo=repo, epic_issue_number=epic_issue_number
            )

        def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
            return repository.list_story_work_item_ids(story_issue_number)

        def get_work_item(self, work_id: str) -> Any:
            return repository.get_work_item(work_id)

        def get_epic_execution_state(self, *, repo: str, epic_issue_number: int) -> Any:
            return None

        def upsert_epic_execution_state(self, state: Any) -> None:
            return None

        def record_operator_request(self, request: Any) -> int | None:
            return None

    class EpicIterationPreview(Exception):
        """Exception to capture selected stories."""

        def __init__(self, selected: list[int]) -> None:
            super().__init__("epic iteration preview selected stories")
            self.selected_story_issue_numbers = selected

    def preview_story_runner(story: ProgramStory) -> None:
        selected = captured_story_issue_numbers or [story.issue_number]
        raise EpicIterationPreview(list(selected))

    def preview_story_batch_selector(
        *, stories: list[ProgramStory], repository: Any, max_batch_size: int = 1
    ) -> list[ProgramStory]:
        selected_batch = select_story_batch(
            stories=stories,
            repository=PreviewRepository(),
            max_batch_size=max_batch_size,
        )
        captured_story_issue_numbers[:] = [
            story.issue_number for story in selected_batch
        ]
        return selected_batch

    preview_repository = PreviewRepository()

    try:
        effective_runner(
            repo=repo,
            epic_issue_number=epic_issue_number,
            repository=preview_repository,
            story_runner=preview_story_runner,
            story_batch_selector=preview_story_batch_selector,
            max_parallel_stories=max_parallel_stories,
        )
    except EpicIterationPreview as preview:
        return preview.selected_story_issue_numbers

    return []  # Should not reach here


def select_story_completion_candidates(
    *,
    repo: str,
    repository: ControlPlaneRepository,
    story_completion_candidates: list[dict[str, Any]],
    running_story_issue_numbers: set[int],
    available_capacity: int,
    epic_story_batch_size: int = 1,
) -> list[int]:
    """
    Select story completion candidates.

    Args:
        repo: Repository name
        repository: Repository instance
        story_completion_candidates: List of candidate stories
        running_story_issue_numbers: Set of running story issue numbers
        available_capacity: Available capacity
        epic_story_batch_size: Batch size for epic iteration

    Returns:
        List of selected story issue numbers
    """
    if available_capacity <= 0 or not story_completion_candidates:
        return []

    selected_story_issue_numbers: list[int] = []
    selected_story_issue_number_set: set[int] = set()

    for candidate in story_completion_candidates:
        if len(selected_story_issue_numbers) >= available_capacity:
            break

        story_issue_number = candidate.get("story_issue_number")
        if story_issue_number is None:
            continue

        story_issue_number = int(story_issue_number)

        if story_issue_number in running_story_issue_numbers:
            continue
        if story_issue_number in selected_story_issue_number_set:
            continue

        selected_story_issue_numbers.append(story_issue_number)
        selected_story_issue_number_set.add(story_issue_number)
        running_story_issue_numbers.add(story_issue_number)

    return selected_story_issue_numbers
