from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from taskplane import hierarchy_api
from taskplane import system_status_api
from taskplane.settings import TaskplaneConfig


def test_system_status_route_is_reexported_from_dedicated_module():
    assert hierarchy_api.get_system_status is system_status_api.get_system_status


def test_get_system_status_returns_config_and_repo_summary(monkeypatch):
    client = TestClient(hierarchy_api.app)

    class FakeConnection:
        def close(self):
            return None

    monkeypatch.setattr(
        hierarchy_api,
        "load_taskplane_config",
        lambda: TaskplaneConfig(
            source_path=Path("/tmp/taskplane.toml"),
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={"owner/repo": "/workspace/repo"},
            console_repo_log_dirs={"owner/repo": "/tmp/taskplane-logs"},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        ),
    )
    monkeypatch.setattr(hierarchy_api, "_get_connection", lambda: FakeConnection())
    monkeypatch.setattr(
        hierarchy_api,
        "list_repositories",
        lambda connection: {"repositories": [{"repo": "owner/repo"}]},
    )
    monkeypatch.setattr(hierarchy_api.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    response = client.get("/api/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config_source"] == "/tmp/taskplane.toml"
    assert payload["postgres_dsn_configured"] is True
    assert payload["database_connected"] is True
    assert payload["configured_repos"][0]["repo"] == "owner/repo"
    assert payload["configured_repos"][0]["workdir"] == "/workspace/repo"
    assert payload["discovered_repositories"] == ["owner/repo"]
    assert payload["commands"]["docker"]["available"] is True


def test_get_system_status_degrades_when_database_unavailable(monkeypatch):
    client = TestClient(hierarchy_api.app)

    monkeypatch.setattr(
        hierarchy_api,
        "load_taskplane_config",
        lambda: TaskplaneConfig(
            source_path=None,
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            console_repo_workdirs={},
            console_repo_log_dirs={},
            dev_compose_file=Path("ops/docker-compose.nocodb.yml"),
            dev_env_file=Path(".env"),
        ),
    )

    def raise_connection_error():
        raise RuntimeError("TASKPLANE_DSN is required")

    monkeypatch.setattr(hierarchy_api, "_get_connection", raise_connection_error)
    monkeypatch.setattr(hierarchy_api.shutil, "which", lambda binary: None)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database_connected"] is False
    assert payload["database_error"] == "TASKPLANE_DSN is required"
    assert payload["commands"]["docker"]["available"] is False
    assert payload["configured_repos"] == []
