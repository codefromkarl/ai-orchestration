from __future__ import annotations

from pathlib import Path


def test_dev_up_runs_compose_and_core_migrations(tmp_path):
    from taskplane.dev_cli import main
    from taskplane.settings import TaskplaneConfig

    captured: list[list[str]] = []

    def fake_config_loader():
        return TaskplaneConfig(
            source_path=tmp_path / "taskplane.toml",
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={},
            console_repo_log_dirs={},
            supervisor_repo_story_executor_commands={},
            supervisor_repo_story_verifier_commands={},
            supervisor_repo_story_force_shell_executor={},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        )

    def fake_runner(command: list[str]):
        captured.append(command)

    exit_code = main(
        ["up"],
        config_loader=fake_config_loader,
        command_runner=fake_runner,
        psql_resolver=lambda: "/usr/bin/psql",
        project_root=tmp_path,
    )

    assert exit_code == 0
    assert captured[0] == [
        "docker",
        "compose",
        "--env-file",
        str(tmp_path / ".env"),
        "-f",
        str(tmp_path / "ops/docker-compose.nocodb.yml"),
        "up",
        "-d",
    ]
    assert captured[1] == [
        "psql",
        "postgresql://user:pass@localhost:5432/taskplane",
        "-f",
        str(tmp_path / "sql" / "control_plane_schema.sql"),
    ]
    assert captured[-1] == [
        "psql",
        "postgresql://user:pass@localhost:5432/taskplane",
        "-f",
        str(tmp_path / "sql" / "009_orchestrator_session.sql"),
    ]
    assert len(captured) == 10


def test_dev_up_falls_back_to_psycopg_when_psql_is_missing(tmp_path):
    from taskplane.dev_cli import main
    from taskplane.settings import TaskplaneConfig

    migration_calls: list[tuple[str, str]] = []

    def fake_config_loader():
        return TaskplaneConfig(
            source_path=tmp_path / "taskplane.toml",
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={},
            console_repo_log_dirs={},
            supervisor_repo_story_executor_commands={},
            supervisor_repo_story_verifier_commands={},
            supervisor_repo_story_force_shell_executor={},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        )

    def fake_migration_runner(*, dsn: str, sql_file: Path):
        migration_calls.append((dsn, str(sql_file)))

    exit_code = main(
        ["up", "--skip-compose"],
        config_loader=fake_config_loader,
        command_runner=lambda command: None,
        migration_runner=fake_migration_runner,
        psql_resolver=lambda: None,
        project_root=tmp_path,
    )

    assert exit_code == 0
    assert len(migration_calls) == 9
    assert migration_calls[0] == (
        "postgresql://user:pass@localhost:5432/taskplane",
        str(tmp_path / "sql" / "control_plane_schema.sql"),
    )


def test_dev_supervise_once_uses_repo_mappings_from_taskplane_config(tmp_path):
    from taskplane.dev_cli import main
    from taskplane.settings import TaskplaneConfig

    captured: dict[str, object] = {}

    def fake_config_loader():
        return TaskplaneConfig(
            source_path=tmp_path / "taskplane.toml",
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={"demo/taskplane": str(tmp_path)},
            console_repo_log_dirs={"demo/taskplane": str(tmp_path / "logs")},
            supervisor_repo_story_executor_commands={
                "demo/taskplane": "python3 -m taskplane.codex_task_executor"
            },
            supervisor_repo_story_verifier_commands={
                "demo/taskplane": "python3 -m taskplane.task_verifier"
            },
            supervisor_repo_story_force_shell_executor={"demo/taskplane": False},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_connection_factory(dsn: str):
        captured["dsn"] = dsn
        return FakeConnection()

    def fake_iteration_runner(**kwargs):
        captured.update(kwargs)
        return 1

    exit_code = main(
        ["supervise", "--repo", "demo/taskplane", "--once"],
        config_loader=fake_config_loader,
        connection_factory=fake_connection_factory,
        supervisor_iteration_runner=fake_iteration_runner,
        project_root=tmp_path,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/taskplane"
    assert captured["repo"] == "demo/taskplane"
    assert captured["project_dir"] == tmp_path
    assert captured["log_dir"] == tmp_path / "logs"
    assert captured["worktree_root"] == tmp_path / ".taskplane" / "worktrees"
    assert (
        captured["story_executor_command"] == "python3 -m taskplane.codex_task_executor"
    )
    assert captured["story_verifier_command"] == "python3 -m taskplane.task_verifier"
    assert captured["story_force_shell_executor"] is False
