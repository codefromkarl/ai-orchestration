from stardrifter_orchestration_mvp.models import StoryRunResult
from stardrifter_orchestration_mvp.story_runner_cli import main


def test_story_runner_cli_loads_story_items_and_runs(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return object()

    def fake_story_loader(*, repository, story_issue_number: int):
        captured["repository"] = repository
        captured["story_issue_number"] = story_issue_number
        return ["issue-56", "issue-57"]

    def fake_story_runner(
        *,
        story_issue_number: int,
        story_work_item_ids,
        repository,
        context,
        worker_name: str,
        executor,
        verifier,
        story_verifier=None,
        committer,
        story_integrator=None,
        workspace_manager=None,
    ):
        captured["worker_name"] = worker_name
        captured["story_work_item_ids"] = story_work_item_ids
        captured["committer"] = committer
        captured["story_integrator"] = story_integrator
        captured["workspace_manager"] = workspace_manager
        return StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=["issue-56", "issue-57"],
            blocked_work_item_ids=[],
            remaining_work_item_ids=[],
            story_complete=True,
        )

    exit_code = main(
        [
            "--story-issue-number",
            "29",
            "--worker-name",
            "worker-a",
            "--allowed-wave",
            "wave-2",
        ],
        repository_builder=fake_repository_builder,
        story_loader=fake_story_loader,
        story_runner=fake_story_runner,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["story_issue_number"] == 29
    assert captured["story_work_item_ids"] == ["issue-56", "issue-57"]
    assert captured["story_integrator"] is None
    assert "story 29 complete" in capsys.readouterr().out


def test_story_runner_cli_builds_shell_adapters_when_commands_are_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_executor_builder(*, command_template: str, workdir):
        captured["executor_command"] = command_template
        captured["executor_workdir"] = workdir
        return "executor"

    def fake_verifier_builder(*, command_template: str, workdir, check_type: str):
        captured["verifier_command"] = command_template
        captured["verifier_workdir"] = workdir
        captured["verifier_check_type"] = check_type
        return "verifier"

    def fake_committer_builder(*, workdir):
        captured["committer_workdir"] = workdir
        return "committer"

    def fake_story_runner(
        *,
        story_issue_number: int,
        story_work_item_ids,
        repository,
        context,
        worker_name: str,
        executor,
        verifier,
        story_verifier=None,
        committer,
        story_integrator=None,
        workspace_manager=None,
    ):
        captured["executor"] = executor
        captured["verifier"] = verifier
        captured["committer"] = committer
        captured["story_integrator"] = story_integrator
        captured["workspace_manager"] = workspace_manager
        return StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=[],
            blocked_work_item_ids=["issue-56"],
            remaining_work_item_ids=["issue-57"],
            story_complete=False,
        )

    exit_code = main(
        [
            "--story-issue-number",
            "29",
            "--workdir",
            str(tmp_path),
            "--executor-command",
            "python3 -m stardrifter_orchestration_mvp.opencode_task_executor",
            "--verifier-command",
            "python3 -m stardrifter_orchestration_mvp.task_verifier",
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-56", "issue-57"],
        story_runner=fake_story_runner,
        executor_builder=fake_executor_builder,
        verifier_builder=fake_verifier_builder,
        story_verifier_builder=fake_verifier_builder,
        committer_builder=fake_committer_builder,
    )

    assert exit_code == 0
    assert (
        captured["executor_command"]
        == "python3 -m stardrifter_orchestration_mvp.opencode_task_executor"
    )
    assert (
        captured["verifier_command"]
        == "python3 -m stardrifter_orchestration_mvp.task_verifier"
    )
    assert captured["executor_workdir"] == tmp_path
    assert captured["verifier_workdir"] == tmp_path
    assert captured["committer_workdir"] == tmp_path
    assert captured["verifier_check_type"] == "pytest"
    assert captured["executor"] == "executor"
    assert captured["verifier"] == "verifier"
    assert captured["committer"] == "committer"
    assert captured["story_integrator"] is None


def test_story_runner_cli_uses_task_verifier_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_verifier_builder(*, command_template: str, workdir, check_type: str):
        captured["verifier_command"] = command_template
        captured["verifier_workdir"] = workdir
        captured["verifier_check_type"] = check_type
        return "verifier"

    def fake_story_runner(
        *,
        story_issue_number: int,
        story_work_item_ids,
        repository,
        context,
        worker_name: str,
        executor,
        verifier,
        story_verifier=None,
        committer,
        story_integrator=None,
        workspace_manager=None,
    ):
        captured["verifier"] = verifier
        return StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=[],
            blocked_work_item_ids=[],
            remaining_work_item_ids=["issue-56"],
            story_complete=False,
        )

    exit_code = main(
        [
            "--story-issue-number",
            "29",
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-56"],
        story_runner=fake_story_runner,
        verifier_builder=fake_verifier_builder,
        committer_builder=lambda *, workdir: "committer",
    )

    assert exit_code == 0
    assert (
        captured["verifier_command"]
        == "python3 -m stardrifter_orchestration_mvp.task_verifier"
    )
    assert captured["verifier_workdir"] == tmp_path
    assert captured["verifier_check_type"] == "pytest"
    assert captured["verifier"] == "verifier"


def test_story_runner_cli_builds_story_verifier_when_command_is_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_verifier_builder(*, command_template: str, workdir, check_type: str):
        if "tests/story" in command_template:
            captured["story_verifier_command"] = command_template
            captured["story_verifier_workdir"] = workdir
            captured["story_verifier_check_type"] = check_type
            return "story-verifier"
        return "task-verifier"

    def fake_story_runner(
        *,
        story_issue_number: int,
        story_work_item_ids,
        repository,
        context,
        worker_name: str,
        executor,
        verifier,
        story_verifier=None,
        committer,
        story_integrator=None,
        workspace_manager=None,
    ):
        captured["story_verifier"] = story_verifier
        return StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=[],
            blocked_work_item_ids=["issue-56"],
            remaining_work_item_ids=["issue-57"],
            story_complete=False,
        )

    exit_code = main(
        [
            "--story-issue-number",
            "29",
            "--workdir",
            str(tmp_path),
            "--story-verifier-command",
            "python3 -m pytest -q tests/story/test_story_29.py",
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-56", "issue-57"],
        story_runner=fake_story_runner,
        verifier_builder=fake_verifier_builder,
        story_verifier_builder=fake_verifier_builder,
        committer_builder=lambda *, workdir: "committer",
    )

    assert exit_code == 0
    assert captured["story_verifier_command"] == (
        "python3 -m pytest -q tests/story/test_story_29.py"
    )
    assert captured["story_verifier_workdir"] == tmp_path
    assert captured["story_verifier_check_type"] == "pytest"
    assert captured["story_verifier"] == "story-verifier"


def test_story_runner_cli_builds_workspace_manager_when_worktree_root_is_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_story_integrator_builder(
        *, repo_root, ignored_dirty_path_prefixes=(), promotion_repo_root=None
    ):
        captured["story_integrator_repo_root"] = repo_root
        captured["ignored_dirty_path_prefixes"] = ignored_dirty_path_prefixes
        captured["promotion_repo_root"] = promotion_repo_root
        return "story-integrator"

    def fake_story_runner(
        *,
        story_issue_number: int,
        story_work_item_ids,
        repository,
        context,
        worker_name: str,
        executor,
        verifier,
        story_verifier=None,
        committer,
        story_integrator=None,
        workspace_manager=None,
    ):
        captured["story_integrator"] = story_integrator
        captured["workspace_manager"] = workspace_manager
        return StoryRunResult(
            story_issue_number=story_issue_number,
            completed_work_item_ids=[],
            blocked_work_item_ids=[],
            remaining_work_item_ids=["issue-56"],
            story_complete=False,
        )

    exit_code = main(
        [
            "--story-issue-number",
            "29",
            "--workdir",
            str(tmp_path),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--promotion-repo-root",
            str(tmp_path / "promotion"),
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-56"],
        story_runner=fake_story_runner,
        story_integrator_builder=fake_story_integrator_builder,
    )

    assert exit_code == 0
    assert captured["workspace_manager"] is not None
    assert captured["story_integrator_repo_root"] == tmp_path
    assert captured["ignored_dirty_path_prefixes"] == ("worktrees/",)
    assert captured["promotion_repo_root"] == tmp_path / "promotion"
    assert captured["story_integrator"] == "story-integrator"
