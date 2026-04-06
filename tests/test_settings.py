from __future__ import annotations

from pathlib import Path


def test_load_taskplane_config_reads_taskplane_toml(tmp_path, monkeypatch):
    from taskplane.settings import load_taskplane_config

    config_path = tmp_path / "taskplane.toml"
    config_path.write_text(
        """
[postgres]
dsn = "postgresql://user:pass@localhost:5432/taskplane"

[console.repo_workdirs]
"owner/repo" = "/workspace/repo"

[console.repo_log_dirs]
"owner/repo" = "/tmp/taskplane-logs"

[supervisor.repo_story_executor_commands]
"owner/repo" = "python3 -m taskplane.codex_task_executor"

[supervisor.repo_story_verifier_commands]
"owner/repo" = "python3 -m taskplane.task_verifier"

[supervisor.repo_story_force_shell_executor]
"owner/repo" = false

[dev]
compose_file = "ops/docker-compose.nocodb.yml"
env_file = ".env.local"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_taskplane_config()

    assert config.source_path == config_path
    assert config.postgres_dsn == "postgresql://user:pass@localhost:5432/taskplane"
    assert config.console_repo_workdirs == {"owner/repo": "/workspace/repo"}
    assert config.console_repo_log_dirs == {"owner/repo": "/tmp/taskplane-logs"}
    assert config.supervisor_repo_story_executor_commands == {
        "owner/repo": "python3 -m taskplane.codex_task_executor"
    }
    assert config.supervisor_repo_story_verifier_commands == {
        "owner/repo": "python3 -m taskplane.task_verifier"
    }
    assert config.supervisor_repo_story_force_shell_executor == {"owner/repo": False}
    assert config.dev_compose_file == Path("ops/docker-compose.nocodb.yml")
    assert config.dev_env_file == Path(".env.local")


def test_load_taskplane_config_allows_env_override(tmp_path, monkeypatch):
    from taskplane.settings import load_taskplane_config

    (tmp_path / "taskplane.toml").write_text(
        """
[postgres]
dsn = "postgresql://from-file"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TASKPLANE_DSN", "postgresql://from-env")

    config = load_taskplane_config()

    assert config.postgres_dsn == "postgresql://from-env"


def test_load_postgres_settings_uses_taskplane_toml(tmp_path, monkeypatch):
    from taskplane.settings import load_postgres_settings_from_env

    (tmp_path / "taskplane.toml").write_text(
        """
[postgres]
dsn = "postgresql://user:pass@localhost:5432/taskplane"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_postgres_settings_from_env()

    assert settings.dsn == "postgresql://user:pass@localhost:5432/taskplane"


def test_load_taskplane_config_allows_env_override_for_supervisor_story_commands(
    tmp_path, monkeypatch
):
    from taskplane.settings import load_taskplane_config

    (tmp_path / "taskplane.toml").write_text(
        """
[supervisor.repo_story_executor_commands]
"owner/repo" = "python3 -m taskplane.codex_task_executor"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "TASKPLANE_SUPERVISOR_REPO_STORY_EXECUTOR_COMMANDS_JSON",
        '{"demo/taskplane":"python3 -m taskplane.opencode_task_executor"}',
    )
    monkeypatch.setenv(
        "TASKPLANE_SUPERVISOR_REPO_STORY_FORCE_SHELL_EXECUTOR_JSON",
        '{"demo/taskplane":true}',
    )

    config = load_taskplane_config()

    assert config.supervisor_repo_story_executor_commands == {
        "demo/taskplane": "python3 -m taskplane.opencode_task_executor"
    }
    assert config.supervisor_repo_story_force_shell_executor == {
        "demo/taskplane": True
    }
