from pathlib import Path

from stardrifter_orchestration_mvp.job_launcher import build_story_command


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
