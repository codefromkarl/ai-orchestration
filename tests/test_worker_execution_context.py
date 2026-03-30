from pathlib import Path

from stardrifter_orchestration_mvp.models import VerificationEvidence, WorkItem
from stardrifter_orchestration_mvp.repository import InMemoryControlPlaneRepository
from stardrifter_orchestration_mvp.worker import (
    _build_execution_context,
    _run_verifier_with_context,
)


def test_build_execution_context_keeps_default_fresh_session_policy():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-40",
                title="fresh session context",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=40,
                canonical_story_issue_number=12,
                story_issue_numbers=(12, 13),
                planned_paths=("src/stardrifter_engine/runtime.py",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    context = _build_execution_context(
        repository=repository,
        work_id="task-40",
        workspace_path=Path("/tmp/task-40"),
    )

    assert context.work_id == "task-40"
    assert context.title == "fresh session context"
    assert context.repo == "codefromkarl/stardrifter"
    assert context.source_issue_number == 40
    assert context.canonical_story_issue_number == 12
    assert context.story_issue_numbers == (12, 13)
    assert context.planned_paths == ("src/stardrifter_engine/runtime.py",)
    assert context.workspace_path == "/tmp/task-40"
    assert context.project_dir == "/tmp/task-40"
    assert context.session_policy == "fresh_session"
    assert context.resume_hint is None


def test_build_execution_context_marks_interrupted_retryable_as_resume_candidate():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-41",
                title="resume session context",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                last_failure_reason="interrupted_retryable",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    context = _build_execution_context(
        repository=repository,
        work_id="task-41",
        workspace_path=None,
    )

    assert context.session_policy == "resume_candidate"
    assert context.resume_hint == "interrupted_retryable"
    assert context.workspace_path is None
    assert context.project_dir is None


def test_run_verifier_with_context_passes_execution_context_only_when_supported():
    work_item = WorkItem(
        id="task-42",
        title="verifier context",
        lane="Lane 06",
        wave="wave-5",
        status="pending",
    )
    repository = InMemoryControlPlaneRepository(
        work_items=[work_item],
        dependencies=[],
        targets_by_work_id={},
    )
    execution_context = _build_execution_context(
        repository=repository,
        work_id="task-42",
        workspace_path=Path("/tmp/task-42"),
    )
    captured: dict[str, object] = {}

    def verifier_accepting_context(
        work_item: WorkItem,
        workspace_path=None,
        execution_context=None,
    ) -> VerificationEvidence:
        captured["accepting_context"] = execution_context
        return VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        )

    def verifier_without_context(
        work_item: WorkItem,
        workspace_path=None,
    ) -> VerificationEvidence:
        captured["without_context_path"] = workspace_path
        return VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        )

    verification_with_context = _run_verifier_with_context(
        verifier=verifier_accepting_context,
        work_item=work_item,
        workspace_path=Path("/tmp/task-42"),
        execution_context=execution_context,
    )
    verification_without_context = _run_verifier_with_context(
        verifier=verifier_without_context,
        work_item=work_item,
        workspace_path=Path("/tmp/task-42"),
        execution_context=execution_context,
    )

    assert verification_with_context.passed is True
    assert captured["accepting_context"] == execution_context
    assert verification_without_context.passed is True
    assert captured["without_context_path"] == Path("/tmp/task-42")
