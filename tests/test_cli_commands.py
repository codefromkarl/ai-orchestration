from pathlib import Path

from stardrifter_orchestration_mvp.cli import main
from stardrifter_orchestration_mvp.models import (
    ExecutionGuardrailContext,
    VerificationEvidence,
)
from stardrifter_orchestration_mvp.worker import ExecutionResult, WorkerCycleResult


def _fake_executor(*args, **kwargs) -> ExecutionResult:
    return ExecutionResult(success=True, summary="ok")


def _fake_verifier(*args, **kwargs) -> VerificationEvidence:
    return VerificationEvidence(
        work_id="task",
        check_type="pytest",
        command="pytest",
        passed=True,
        output_digest="ok",
    )


def test_cli_main_builds_shell_adapters_when_commands_are_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        return object()

    def fake_executor_builder(*, command_template: str, workdir: Path):
        captured["executor_command"] = command_template
        captured["executor_workdir"] = workdir
        return _fake_executor

    def fake_verifier_builder(*, command_template: str, workdir: Path, check_type: str):
        captured["verifier_command"] = command_template
        captured["verifier_workdir"] = workdir
        captured["verifier_check_type"] = check_type
        return _fake_verifier

    def fake_committer_builder(*, workdir: Path):
        captured["committer_workdir"] = workdir
        return object()

    def fake_cycle_runner(
        *,
        repository,
        context: ExecutionGuardrailContext,
        worker_name: str,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
    ):
        captured["executor"] = executor
        captured["verifier"] = verifier
        captured["committer"] = committer
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        [
            "--executor-command",
            "python3 -m pytest -q tests/test_worker.py",
            "--verifier-command",
            "python3 -m pytest -q",
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=fake_repository_builder,
        cycle_runner=fake_cycle_runner,
        executor_builder=fake_executor_builder,
        verifier_builder=fake_verifier_builder,
        committer_builder=fake_committer_builder,
    )

    assert exit_code == 0
    assert captured["executor_command"] == "python3 -m pytest -q tests/test_worker.py"
    assert captured["verifier_command"] == "python3 -m pytest -q"
    assert captured["executor_workdir"] == tmp_path
    assert captured["verifier_workdir"] == tmp_path
    assert captured["committer_workdir"] == tmp_path
    assert captured["verifier_check_type"] == "pytest"


def test_story_runner_cli_builds_routed_task_executor_when_command_is_provided(
    monkeypatch, tmp_path
):
    from stardrifter_orchestration_mvp.story_runner_cli import main as story_main

    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_executor_builder(*, command_template: str, workdir: Path):
        captured["executor_command"] = command_template
        captured["executor_workdir"] = workdir
        return _fake_executor

    def fake_story_runner(**kwargs):
        captured["executor"] = kwargs["executor"]
        return type(
            "StoryRunResultStub",
            (),
            {
                "story_complete": False,
                "blocked_work_item_ids": [],
                "remaining_work_item_ids": ["issue-139"],
                "merge_blocked_reason": None,
            },
        )()

    exit_code = story_main(
        [
            "--story-issue-number",
            "130",
            "--executor-command",
            "python3 -m stardrifter_orchestration_mvp.opencode_task_executor",
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-139"],
        story_runner=fake_story_runner,
        executor_builder=fake_executor_builder,
        verifier_builder=lambda **kwargs: _fake_verifier,
        committer_builder=lambda **kwargs: object(),
        story_integrator_builder=lambda **kwargs: object(),
    )

    assert exit_code == 0
    assert captured["executor_command"] == (
        "python3 -m stardrifter_orchestration_mvp.opencode_task_executor"
    )
    assert captured["executor_workdir"] == tmp_path
