from datetime import datetime, timedelta, timezone

from stardrifter_orchestration_mvp.epic_runner import (
    run_epic_iteration,
    run_epic_until_settled,
)
from stardrifter_orchestration_mvp.models import (
    EPIC_RUNTIME_STATUSES,
    EpicExecutionState,
    OperatorRequest,
    ProgramStory,
    StoryRunResult,
)
from stardrifter_orchestration_mvp.repository import InMemoryControlPlaneRepository


def test_run_epic_until_settled_records_done_state_after_serial_story_completion():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
        ],
    )
    calls: list[int] = []
    now = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=["issue-201"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
        now=now,
    )

    assert result.epic_issue_number == 13
    assert result.epic_complete is True
    assert result.completed_story_issue_numbers == [41, 42]
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == []
    assert calls == [42]
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="done",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(),
        blocked_reason_code="epic_complete",
        operator_attention_required=False,
        last_progress_at=now,
        stalled_since=None,
        verification_status="passed",
        verification_reason_code=None,
        last_verification_at=now,
        verification_summary="epic verification passed",
    )


def test_run_epic_until_settled_requires_epic_verification_before_done():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
        ],
    )
    now = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=["issue-201"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        ),
        epic_verifier=lambda **kwargs: {
            "passed": False,
            "summary": "epic regression failed",
            "reason_code": "epic_verification_failed",
        },
        now=now,
    )

    assert result.epic_complete is False
    assert result.reason_code == "epic_verification_failed"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(),
        blocked_reason_code="epic_verification_failed",
        operator_attention_required=True,
        last_progress_at=now,
        stalled_since=None,
        verification_status="failed",
        verification_reason_code="epic_verification_failed",
        last_verification_at=now,
        verification_summary="epic regression failed",
    )


def test_run_epic_until_settled_stops_after_blocked_story_and_persists_state():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    calls: list[int] = []
    now = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=[],
                blocked_work_item_ids=["issue-301"],
                remaining_work_item_ids=[],
                story_complete=False,
            )
        ),
        now=now,
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == []
    assert result.blocked_story_issue_numbers == [41]
    assert result.remaining_story_issue_numbers == [42]
    assert result.reason_code == "all_remaining_stories_blocked"
    assert calls == [41]
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(),
        blocked_story_issue_numbers=(41,),
        remaining_story_issue_numbers=(42,),
        blocked_reason_code="all_remaining_stories_blocked",
        operator_attention_required=True,
    )
    assert repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == [
        OperatorRequest(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            reason_code="all_remaining_stories_blocked",
            summary="Epic #13 needs operator attention: 1 blocked story is preventing the remaining 1 story from safely running.",
            remaining_story_issue_numbers=(42,),
            blocked_story_issue_numbers=(41,),
            status="open",
            opened_at=now,
        )
    ]


def test_run_epic_until_settled_does_not_mark_empty_epic_complete():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[],
    )

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=[],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=False,
        ),
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == []
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == []
    assert result.reason_code == "epic_has_no_stories"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="backlog",
        blocked_reason_code="epic_has_no_stories",
        operator_attention_required=False,
    )


def test_epic_runtime_statuses_are_centralized_to_current_runtime_vocabulary():
    assert EPIC_RUNTIME_STATUSES == (
        "backlog",
        "active",
        "awaiting_operator",
        "done",
    )


def test_run_epic_iteration_persists_single_iteration_state_without_wrapper_loop_changes():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    now = datetime(2026, 3, 1, 15, 0, tzinfo=timezone.utc)
    calls: list[int] = []

    result = run_epic_iteration(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=[f"issue-{story.issue_number}"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
        now=now,
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == [41, 42]
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == [43]
    assert result.reason_code == "epic_incomplete"
    assert calls == [42]
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="active",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(43,),
        blocked_reason_code="epic_incomplete",
        operator_attention_required=False,
        last_progress_at=now,
        stalled_since=None,
    )


def test_run_epic_until_settled_remains_serial_by_default():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
        ],
    )
    calls: list[int] = []

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=[f"issue-{story.issue_number}"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == [41]
    assert result.remaining_story_issue_numbers == [42]
    assert result.reason_code == "epic_incomplete"
    assert calls == [41]


def test_run_epic_until_settled_marks_no_batch_safe_stories_as_awaiting_operator():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=[f"issue-{story.issue_number}"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        ),
        story_batch_selector=lambda **kwargs: [],
        max_parallel_stories=2,
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == []
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == [41, 42, 43]
    assert result.reason_code == "no_batch_safe_stories_available"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(41, 42, 43),
        blocked_reason_code="no_batch_safe_stories_available",
        operator_attention_required=True,
    )
    requests = repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )
    assert len(requests) == 1
    assert requests[0] == OperatorRequest(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="no_batch_safe_stories_available",
        summary="Epic #13 needs operator attention: no safe story batch is available while 3 stories remain pending.",
        remaining_story_issue_numbers=(41, 42, 43),
        blocked_story_issue_numbers=(),
        status="open",
        opened_at=requests[0].opened_at,
    )


def test_run_epic_until_settled_retries_multi_story_selection_with_batch_size_one_before_escalating():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    selector_calls: list[int] = []
    story_runner_calls: list[int] = []
    now = datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)

    def selector(**kwargs: object) -> list[ProgramStory]:
        max_batch_size = kwargs["max_batch_size"]
        assert isinstance(max_batch_size, int)
        selector_calls.append(max_batch_size)
        stories = kwargs["stories"]
        assert isinstance(stories, list)
        if max_batch_size > 1:
            return []
        return [stories[0]]

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            story_runner_calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=[f"issue-{story.issue_number}"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
        story_batch_selector=selector,
        max_parallel_stories=2,
        now=now,
    )

    assert selector_calls == [2, 1]
    assert story_runner_calls == [41]
    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == [41]
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == [42, 43]
    assert result.reason_code == "epic_incomplete"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="active",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(42, 43),
        blocked_reason_code="epic_incomplete",
        operator_attention_required=False,
        last_progress_at=now,
        stalled_since=None,
    )
    assert (
        repository.list_operator_requests(
            repo="codefromkarl/stardrifter", epic_issue_number=13
        )
        == []
    )


def test_run_epic_until_settled_still_escalates_hard_blockers_after_degraded_batch_retry():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="blocked",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    selector_calls: list[int] = []

    def selector(**kwargs: object) -> list[ProgramStory]:
        max_batch_size = kwargs["max_batch_size"]
        assert isinstance(max_batch_size, int)
        selector_calls.append(max_batch_size)
        return []

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=[f"issue-{story.issue_number}"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        ),
        story_batch_selector=selector,
        max_parallel_stories=2,
    )

    assert selector_calls == [2, 1]
    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == []
    assert result.blocked_story_issue_numbers == [41]
    assert result.remaining_story_issue_numbers == [42, 43]
    assert result.reason_code == "all_remaining_stories_blocked"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(),
        blocked_story_issue_numbers=(41,),
        remaining_story_issue_numbers=(42, 43),
        blocked_reason_code="all_remaining_stories_blocked",
        operator_attention_required=True,
    )
    requests = repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )
    assert len(requests) == 1
    assert requests[0] == OperatorRequest(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="all_remaining_stories_blocked",
        summary="Epic #13 needs operator attention: 1 blocked story is preventing the remaining 2 stories from safely running.",
        remaining_story_issue_numbers=(42, 43),
        blocked_story_issue_numbers=(41,),
        status="open",
        opened_at=requests[0].opened_at,
    )


def test_run_epic_until_settled_can_run_explicit_safe_batch_in_tests():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
        ],
    )
    calls: list[int] = []

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: (
            calls.append(story.issue_number)
            or StoryRunResult(
                story_issue_number=story.issue_number,
                completed_work_item_ids=[f"issue-{story.issue_number}"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
        story_batch_selector=lambda **kwargs: kwargs["stories"],
        max_parallel_stories=2,
    )

    assert result.epic_complete is True
    assert result.completed_story_issue_numbers == [41, 42]
    assert result.remaining_story_issue_numbers == []
    assert result.reason_code == "epic_complete"
    assert calls == [41, 42]


def test_run_epic_until_settled_refreshes_progress_when_completed_story_count_increases():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    repository.upsert_epic_execution_state(
        EpicExecutionState(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            status="active",
            completed_story_issue_numbers=(41,),
            blocked_story_issue_numbers=(),
            remaining_story_issue_numbers=(42, 43),
            blocked_reason_code="epic_incomplete",
            operator_attention_required=False,
            last_progress_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            stalled_since=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
        )
    )
    now = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=[f"issue-{story.issue_number}"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        ),
        now=now,
        progress_timeout=timedelta(hours=1),
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == [41, 42]
    assert result.remaining_story_issue_numbers == [43]
    assert result.reason_code == "epic_incomplete"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="active",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(43,),
        blocked_reason_code="epic_incomplete",
        operator_attention_required=False,
        last_progress_at=now,
        stalled_since=None,
    )


def test_run_epic_until_settled_escalates_when_incomplete_epic_stalls_past_timeout():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
            ProgramStory(
                issue_number=43,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 43",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )
    stalled_since = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    repository.upsert_epic_execution_state(
        EpicExecutionState(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            status="active",
            completed_story_issue_numbers=(41, 42),
            blocked_story_issue_numbers=(),
            remaining_story_issue_numbers=(42, 43),
            blocked_reason_code="epic_incomplete",
            operator_attention_required=False,
            last_progress_at=datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc),
            stalled_since=stalled_since,
        )
    )
    now = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)

    result = run_epic_until_settled(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=repository,
        story_runner=lambda story: StoryRunResult(
            story_issue_number=story.issue_number,
            completed_work_item_ids=[f"issue-{story.issue_number}"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        ),
        now=now,
        progress_timeout=timedelta(hours=2),
    )

    assert result.epic_complete is False
    assert result.completed_story_issue_numbers == [41, 42]
    assert result.blocked_story_issue_numbers == []
    assert result.remaining_story_issue_numbers == [43]
    assert result.reason_code == "progress_timeout"
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(43,),
        blocked_reason_code="progress_timeout",
        operator_attention_required=True,
        last_progress_at=datetime(2026, 3, 1, 11, 0, tzinfo=timezone.utc),
        stalled_since=stalled_since,
    )
    requests = repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )
    assert len(requests) == 1
    assert requests[0] == OperatorRequest(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="progress_timeout",
        summary="Epic #13 needs operator attention: progress timed out with 1 remaining story.",
        remaining_story_issue_numbers=(43,),
        blocked_story_issue_numbers=(),
        status="open",
        opened_at=requests[0].opened_at,
    )
