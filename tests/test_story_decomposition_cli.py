from stardrifter_orchestration_mvp.story_decomposition_cli import main
from stardrifter_orchestration_mvp.story_decomposition import StoryDecompositionResult


def test_story_decomposition_cli_runs_and_prints_active(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return object()

    def fake_story_runner(*, repo: str, story_issue_number: int, repository, workdir, decomposer_command: str | None):
        captured["repo"] = repo
        captured["story_issue_number"] = story_issue_number
        captured["repository"] = repository
        captured["workdir"] = workdir
        captured["decomposer_command"] = decomposer_command
        return StoryDecompositionResult(
            story_issue_number=42,
            final_execution_status="active",
            projectable_task_count=2,
            summary="created tasks",
        )

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--story-issue-number",
            "42",
            "--workdir",
            str(tmp_path),
            "--decomposer-command",
            "python3 -m stardrifter_orchestration_mvp.opencode_story_decomposer",
        ],
        repository_builder=fake_repository_builder,
        decomposition_runner=fake_story_runner,
    )

    assert exit_code == 0
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["story_issue_number"] == 42
    assert captured["workdir"] == tmp_path
    assert "story 42 active; tasks=2" in capsys.readouterr().out
