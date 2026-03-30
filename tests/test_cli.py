from stardrifter_orchestration_mvp.cli import main
from stardrifter_orchestration_mvp.models import ExecutionGuardrailContext
from stardrifter_orchestration_mvp.worker import WorkerCycleResult


def _assert_system_exit(callable_obj) -> None:
    try:
        callable_obj()
    except SystemExit:
        return
    raise AssertionError("expected SystemExit")


def test_cli_main_loads_env_builds_repository_and_runs_worker_cycle(
    monkeypatch, capsys
):
    captured: dict[str, object] = {}

    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
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
        captured["repository"] = repository
        captured["context"] = context
        captured["worker_name"] = worker_name
        captured["committer"] = committer
        return WorkerCycleResult(claimed_work_id="task-2")

    exit_code = main(
        [
            "--worker-name",
            "worker-a",
            "--allowed-wave",
            "wave-5",
            "--frozen-prefix",
            "docs/authority/",
        ],
        repository_builder=fake_repository_builder,
        cycle_runner=fake_cycle_runner,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["worker_name"] == "worker-a"
    assert captured["context"] == ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )
    assert "claimed task-2" in capsys.readouterr().out


def test_cli_main_handles_empty_cycle_without_error(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    exit_code = main(
        [],
        repository_builder=lambda *, dsn: object(),
        cycle_runner=lambda **kwargs: WorkerCycleResult(claimed_work_id=None),
    )

    assert exit_code == 0
    assert "no runnable task" in capsys.readouterr().out


def test_cli_main_passes_work_item_ids_when_provided(monkeypatch):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_cycle_runner(
        *,
        repository,
        context,
        worker_name,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
    ):
        captured["work_item_ids"] = work_item_ids
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        [
            "--work-item-id",
            "issue-69",
            "--work-item-id",
            "issue-72",
        ],
        repository_builder=lambda *, dsn: object(),
        cycle_runner=fake_cycle_runner,
    )

    assert exit_code == 0
    assert captured["work_item_ids"] == ["issue-69", "issue-72"]


def test_cli_main_builds_workspace_manager_when_worktree_root_is_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_cycle_runner(
        *,
        repository,
        context,
        worker_name,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
    ):
        captured["workspace_manager"] = workspace_manager
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        [
            "--workdir",
            str(tmp_path),
            "--worktree-root",
            str(tmp_path / "worktrees"),
        ],
        repository_builder=lambda *, dsn: object(),
        cycle_runner=fake_cycle_runner,
    )

    assert exit_code == 0
    assert captured["workspace_manager"] is not None


def test_cli_main_rejects_missing_executor_command_binary(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    _assert_system_exit(
        lambda: main(
            [
                "--workdir",
                str(tmp_path),
                "--executor-command",
                "nonexistent-binary --flag",
            ],
            repository_builder=lambda *, dsn: object(),
            cycle_runner=lambda **kwargs: WorkerCycleResult(claimed_work_id=None),
        )
    )


def test_cli_main_rejects_missing_verifier_command_binary(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    _assert_system_exit(
        lambda: main(
            [
                "--workdir",
                str(tmp_path),
                "--verifier-command",
                "nonexistent-binary --flag",
            ],
            repository_builder=lambda *, dsn: object(),
            cycle_runner=lambda **kwargs: WorkerCycleResult(claimed_work_id=None),
        )
    )


def test_cli_main_rejects_nonexistent_workdir(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    _assert_system_exit(
        lambda: main(
            ["--workdir", str(tmp_path / "missing-dir")],
            repository_builder=lambda *, dsn: object(),
            cycle_runner=lambda **kwargs: WorkerCycleResult(claimed_work_id=None),
        )
    )


def test_cli_main_rejects_worktree_root_under_file_path(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    blocking_file = tmp_path / "not-a-dir"
    blocking_file.write_text("x")

    _assert_system_exit(
        lambda: main(
            [
                "--workdir",
                str(tmp_path),
                "--worktree-root",
                str(blocking_file / "child-worktrees"),
            ],
            repository_builder=lambda *, dsn: object(),
            cycle_runner=lambda **kwargs: WorkerCycleResult(claimed_work_id=None),
        )
    )
