from typing import Any, cast

from stardrifter_orchestration_mvp.epic_decomposition import (
    DecompositionExecutionResult,
    run_shell_epic_decomposer,
    run_epic_decomposition,
)


def test_run_epic_decomposition_promotes_epic_to_active_when_refreshed_stories_include_active_story():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_epic_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "epic_issue_number": 13,
                "epic_title": "[Epic] Runtime orchestration",
                "execution_status": "decomposing",
                "epic_story_count": 0,
                "active_story_count": 0,
                "decomposing_story_count": 0,
                "epic_body": "epic body",
            },
            {
                "epic_issue_number": 13,
                "epic_title": "[Epic] Runtime orchestration",
                "execution_status": "decomposing",
                "epic_story_count": 2,
                "active_story_count": 1,
                "decomposing_story_count": 1,
                "epic_body": "epic body",
            },
        ]
    )

    result = run_epic_decomposition(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=cast(Any, FakeRepository()),
        epic_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created stories",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "active"
    assert result.projectable_story_count == 2
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 13,
        "execution_status": "active",
    }


def test_run_epic_decomposition_marks_epic_needs_refinement_when_refreshed_stories_are_only_decomposing():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_epic_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "epic_issue_number": 13,
                "epic_title": "[Epic] Runtime orchestration",
                "execution_status": "decomposing",
                "epic_story_count": 0,
                "active_story_count": 0,
                "decomposing_story_count": 0,
                "epic_body": "epic body",
            },
            {
                "epic_issue_number": 13,
                "epic_title": "[Epic] Runtime orchestration",
                "execution_status": "decomposing",
                "epic_story_count": 2,
                "active_story_count": 0,
                "decomposing_story_count": 2,
                "epic_body": "epic body",
            },
        ]
    )

    result = run_epic_decomposition(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        repository=cast(Any, FakeRepository()),
        epic_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created only weak stories",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert result.projectable_story_count == 2
    assert "needs refinement" in result.summary
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 13,
        "execution_status": "needs_story_refinement",
    }


def test_run_shell_epic_decomposer_ignores_non_payload_marker_dicts(
    monkeypatch, tmp_path
):
    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(*args, **kwargs):
        return Completed(
            returncode=0,
            stdout="\n".join(
                [
                    'STARDRIFTER_DECOMPOSITION_RESULT_JSON={"outcome":"blocked","summary":"awaiting repository context","reason_code":"awaiting_repository_context"}',
                    'STARDRIFTER_DECOMPOSITION_RESULT_JSON={"type":"step-finish","reason":"stop"}',
                ]
            ),
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_shell_epic_decomposer(
        repo="codefromkarl/stardrifter",
        epic_issue_number=64,
        epic={
            "epic_issue_number": 64,
            "epic_title": "[Epic][Lane 09] Unified Bridge API 统一桥接层",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m stardrifter_orchestration_mvp.opencode_epic_decomposer",
    )

    assert result.success is True
    assert result.outcome == "blocked"
    assert result.reason_code == "awaiting_repository_context"
    assert result.summary == "awaiting repository context"
