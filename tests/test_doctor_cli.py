from __future__ import annotations

from pathlib import Path


def test_doctor_reports_healthy_local_setup(capsys):
    from taskplane.doctor_cli import main
    from taskplane.settings import TaskplaneConfig

    class FakeConnection:
        def close(self):
            return None

    def fake_config_loader():
        return TaskplaneConfig(
            source_path=Path("/tmp/taskplane.toml"),
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={"owner/repo": "/workspace/repo"},
            console_repo_log_dirs={"owner/repo": "/tmp/taskplane-logs"},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        )

    def fake_which(binary: str):
        return f"/usr/bin/{binary}"

    def fake_connector(dsn: str):
        assert dsn == "postgresql://user:pass@localhost:5432/taskplane"
        return FakeConnection()

    exit_code = main(
        ["--repo", "owner/repo"],
        config_loader=fake_config_loader,
        which=fake_which,
        connector=fake_connector,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[ok] config" in captured.out
    assert "[ok] db" in captured.out
    assert "[ok] console repo" in captured.out


def test_doctor_fails_when_repo_mapping_is_missing(capsys):
    from taskplane.doctor_cli import main
    from taskplane.settings import TaskplaneConfig

    def fake_config_loader():
        return TaskplaneConfig(
            source_path=Path("/tmp/taskplane.toml"),
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={},
            console_repo_log_dirs={},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        )

    exit_code = main(
        ["--repo", "owner/repo", "--skip-db"],
        config_loader=fake_config_loader,
        which=lambda binary: f"/usr/bin/{binary}",
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "[fail] console repo" in captured.out
