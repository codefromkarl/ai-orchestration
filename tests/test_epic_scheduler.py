from stardrifter_orchestration_mvp.epic_scheduler import select_story_batch
from stardrifter_orchestration_mvp.models import ExecutionStatus, ProgramStory, WorkItem
from stardrifter_orchestration_mvp.repository import InMemoryControlPlaneRepository


def _story(
    issue_number: int,
    *,
    execution_status: ExecutionStatus = "active",
) -> ProgramStory:
    return ProgramStory(
        issue_number=issue_number,
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        title=f"Story {issue_number}",
        lane="Lane 01",
        complexity="medium",
        program_status="approved",
        execution_status=execution_status,
    )


def _work_item(
    work_id: str,
    *,
    story_issue_number: int,
    planned_paths: tuple[str, ...],
) -> WorkItem:
    return WorkItem(
        id=work_id,
        title=work_id,
        lane="Lane 01",
        wave="wave-2",
        status="ready",
        repo="codefromkarl/stardrifter",
        canonical_story_issue_number=story_issue_number,
        planned_paths=planned_paths,
    )


def test_select_story_batch_excludes_stories_with_unmet_dependencies():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            _work_item(
                "issue-501",
                story_issue_number=41,
                planned_paths=("src/story-41.py",),
            ),
            _work_item(
                "issue-502",
                story_issue_number=42,
                planned_paths=("src/story-42.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
        story_dependencies=[(42, 41)],
    )

    selected = select_story_batch(
        stories=[_story(41), _story(42)],
        repository=repository,
        max_batch_size=2,
    )

    assert [story.issue_number for story in selected] == [41]


def test_select_story_batch_skips_conflicting_paths_and_keeps_non_conflicting_story():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            _work_item(
                "issue-601",
                story_issue_number=41,
                planned_paths=("src/runtime",),
            ),
            _work_item(
                "issue-602",
                story_issue_number=42,
                planned_paths=("src/runtime/player.py",),
            ),
            _work_item(
                "issue-603",
                story_issue_number=43,
                planned_paths=("tests/story_43_test.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    selected = select_story_batch(
        stories=[_story(41), _story(42), _story(43)],
        repository=repository,
        max_batch_size=3,
    )

    assert [story.issue_number for story in selected] == [41, 43]


def test_select_story_batch_treats_missing_planned_paths_as_not_batch_safe():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            _work_item(
                "issue-701",
                story_issue_number=41,
                planned_paths=(),
            ),
            _work_item(
                "issue-702",
                story_issue_number=42,
                planned_paths=("tests/story_42_test.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    selected = select_story_batch(
        stories=[_story(41), _story(42)],
        repository=repository,
        max_batch_size=2,
    )

    assert [story.issue_number for story in selected] == [42]
