from pathlib import Path
import os

from taskplane.job_launcher import build_story_command


def test_build_story_command_default_waves_include_wave_4(
    tmp_path: Path,
) -> None:
    command = build_story_command(
        dsn="postgresql://example",
        story_issue_number=170,
        allowed_waves=(),
        project_dir=tmp_path,
        worktree_root=tmp_path / ".orchestration-worktrees",
        promotion_repo_root=None,
    )

    assert "--allowed-wave wave-4" in command
    assert "--allowed-wave wave-1" in command
    assert "--allowed-wave wave-2" in command
    assert "--allowed-wave wave-3" in command
    assert (
        "python3 -m taskplane.codex_task_executor" in command
    )


def test_build_story_command_respects_executor_and_verifier_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKPLANE_STORY_EXECUTOR_COMMAND", "true")
    monkeypatch.setenv("TASKPLANE_STORY_VERIFIER_COMMAND", "false")
    monkeypatch.setenv("TASKPLANE_STORY_FORCE_SHELL_EXECUTOR", "1")

    command = build_story_command(
        dsn="postgresql://example",
        story_issue_number=170,
        allowed_waves=("wave-1",),
        project_dir=tmp_path,
        worktree_root=tmp_path / ".orchestration-worktrees",
        promotion_repo_root=None,
    )

    assert "export TASKPLANE_FORCE_SHELL_EXECUTOR=1;" in command
    assert "--executor-command true" in command
    assert "--verifier-command false" in command
    assert command.index("export TASKPLANE_FORCE_SHELL_EXECUTOR=1;") < command.index(
        "python3 -m taskplane.story_runner_cli"
    )


def test_build_story_command_prefers_explicit_story_runner_configuration_over_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TASKPLANE_STORY_EXECUTOR_COMMAND", "true")
    monkeypatch.setenv("TASKPLANE_STORY_VERIFIER_COMMAND", "false")
    monkeypatch.setenv("TASKPLANE_STORY_FORCE_SHELL_EXECUTOR", "1")

    command = build_story_command(
        dsn="postgresql://example",
        story_issue_number=170,
        allowed_waves=("wave-2",),
        project_dir=tmp_path,
        worktree_root=None,
        promotion_repo_root=None,
        executor_command="python3 -m taskplane.codex_task_executor",
        verifier_command="python3 -m taskplane.task_verifier",
        force_shell_executor=False,
    )

    assert "--executor-command true" not in command
    assert "--verifier-command false" not in command
    assert "export TASKPLANE_FORCE_SHELL_EXECUTOR=1;" not in command
    assert (
        "--executor-command 'python3 -m taskplane.codex_task_executor'" in command
    )
    assert (
        "--verifier-command 'python3 -m taskplane.task_verifier'" in command
    )


def test_build_story_command_exports_parent_execution_job_pid(
    tmp_path: Path,
) -> None:
    command = build_story_command(
        dsn="postgresql://example",
        story_issue_number=170,
        allowed_waves=("wave-3",),
        project_dir=tmp_path,
        worktree_root=None,
        promotion_repo_root=None,
    )

    assert "export TASKPLANE_EXECUTION_JOB_PID=$$;" in command
