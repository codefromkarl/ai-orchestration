from datetime import datetime, timezone

from taskplane.epic_resume_cli import main
from taskplane.models import (
    EpicExecutionState,
    OperatorRequest,
    ProgramStory,
)
from taskplane.repository import InMemoryControlPlaneRepository


def test_epic_resume_cli_clears_stale_operator_attention_when_no_open_requests_remain(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
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
                execution_status="blocked",
            ),
        ],
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
                last_progress_at=progress_at,
                stalled_since=stalled_since,
            )
        },
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(),
                blocked_story_issue_numbers=(42,),
                status="closed",
            )
        ],
    )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--epic-issue-number", "13"],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(42,),
        remaining_story_issue_numbers=(),
        blocked_reason_code="all_remaining_stories_blocked",
        operator_attention_required=False,
        last_progress_at=progress_at,
        stalled_since=stalled_since,
    )
    assert (
        capsys.readouterr().out.strip()
        == "mode=apply epic=13 status=awaiting_operator operator_attention=false open_requests=0 continue_ready=false"
    )


def test_epic_resume_cli_preserves_operator_attention_when_open_requests_still_exist(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
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
                execution_status="blocked",
            ),
        ],
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
                last_progress_at=progress_at,
                stalled_since=stalled_since,
            )
        },
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(),
                blocked_story_issue_numbers=(42,),
                status="open",
            )
        ],
    )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--epic-issue-number", "13"],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(42,),
        remaining_story_issue_numbers=(),
        blocked_reason_code="all_remaining_stories_blocked",
        operator_attention_required=True,
        last_progress_at=progress_at,
        stalled_since=stalled_since,
    )
    assert (
        capsys.readouterr().out.strip()
        == "mode=apply epic=13 status=awaiting_operator operator_attention=true open_requests=1 continue_ready=false"
    )


def test_epic_resume_cli_dry_run_reports_refreshed_state_without_persisting(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
    initial_state = EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(42,),
        remaining_story_issue_numbers=(),
        blocked_reason_code="all_remaining_stories_blocked",
        operator_attention_required=True,
        last_progress_at=progress_at,
        stalled_since=stalled_since,
    )
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
                execution_status="blocked",
            ),
        ],
        epic_execution_states={("codefromkarl/stardrifter", 13): initial_state},
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(),
                blocked_story_issue_numbers=(42,),
                status="closed",
            )
        ],
    )

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
            "--dry-run",
        ],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
    assert (
        repository.get_epic_execution_state(
            repo="codefromkarl/stardrifter", epic_issue_number=13
        )
        == initial_state
    )
    assert (
        capsys.readouterr().out.strip()
        == "mode=dry-run epic=13 status=awaiting_operator operator_attention=false open_requests=0 continue_ready=false"
    )


def test_epic_resume_cli_recomputes_active_state_when_runtime_is_cleaner_for_supervisor_continuation(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
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
        ],
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
                last_progress_at=progress_at,
                stalled_since=stalled_since,
            )
        },
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(),
                blocked_story_issue_numbers=(42,),
                status="closed",
            )
        ],
    )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--epic-issue-number", "13"],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
    assert (
        capsys.readouterr().out.strip()
        == "mode=apply epic=13 status=active operator_attention=false open_requests=0 continue_ready=true"
    )


def test_epic_resume_cli_recomputes_status_from_current_story_runtime_instead_of_preserving_stale_state(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
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
        ],
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
                last_progress_at=progress_at,
                stalled_since=stalled_since,
            )
        },
        operator_requests=[],
    )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--epic-issue-number", "13"],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="active",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(42,),
        blocked_reason_code="epic_incomplete",
        operator_attention_required=False,
        last_progress_at=progress_at,
        stalled_since=stalled_since,
    )
    assert (
        capsys.readouterr().out.strip()
        == "mode=apply epic=13 status=active operator_attention=false open_requests=0 continue_ready=true"
    )


def test_epic_resume_cli_recomputes_done_state_from_verified_epic_state(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    now = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
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
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
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
                verification_status="passed",
                verification_reason_code=None,
                last_verification_at=now,
                verification_summary="epic verification passed",
            )
        },
        operator_requests=[],
    )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--epic-issue-number", "13"],
        repository_builder=lambda *, dsn: repository,
    )

    assert exit_code == 0
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
    assert (
        capsys.readouterr().out.strip()
        == "mode=apply epic=13 status=done operator_attention=false open_requests=0 continue_ready=false"
    )
