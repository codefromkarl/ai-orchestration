from __future__ import annotations

from pathlib import Path


def test_live_acceptance_cli_main_parses_args_and_calls_runner(tmp_path, capsys):
    from taskplane.live_acceptance_cli import LiveAcceptanceResult, main

    captured: dict[str, object] = {}

    def fake_runner(config):
        captured["config"] = config
        return LiveAcceptanceResult(
            success=True,
            work_status="done",
            session_status="completed",
            wakeup_status="fired",
            execution_job_status="succeeded",
            log_dir=config.run_log_dir,
            planned_path=config.run_planned_path,
            details={"work_id": config.work_id},
        )

    exit_code = main(
        [
            "--dsn",
            "postgresql://user:pass@localhost:5432/taskplane",
            "--repo",
            "codefromkarl/stardrifter",
            "--project-dir",
            str(tmp_path / "project"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--story-issue-number",
            "132",
            "--work-id",
            "issue-191",
            "--suppress-work-id",
            "issue-74",
            "--allowed-wave",
            "Wave0",
            "--story-force-shell-executor",
        ],
        runner=fake_runner,
    )

    assert exit_code == 0
    config = captured["config"]
    assert config.dsn == "postgresql://user:pass@localhost:5432/taskplane"
    assert config.repo == "codefromkarl/stardrifter"
    assert config.story_issue_number == 132
    assert config.work_id == "issue-191"
    assert config.suppress_work_id == "issue-74"
    assert config.allowed_waves == ("Wave0",)
    assert config.story_force_shell_executor is True
    assert "work_status=done" in capsys.readouterr().out


def test_live_acceptance_cli_default_final_executor_command_is_non_mutating():
    from taskplane.live_acceptance_cli import _default_final_executor_command

    command = _default_final_executor_command()

    assert "TASKPLANE_EXECUTION_RESULT_JSON=" in command
    assert "already_satisfied" in command
    assert "without repo mutation" in command
