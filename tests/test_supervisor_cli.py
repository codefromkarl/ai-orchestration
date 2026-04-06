from __future__ import annotations

from taskplane.supervisor_cli import main


def test_supervisor_cli_builds_persistent_runtime_and_passes_to_iteration(tmp_path):
    captured: dict[str, object] = {}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    def fake_connect(dsn: str, row_factory=None):
        captured["dsn"] = dsn
        captured["row_factory"] = row_factory
        return FakeConnection()

    def fake_runtime_builder(connection):
        captured["runtime_connection"] = connection
        return ("session-manager", "wakeup-dispatcher")

    def fake_iteration(**kwargs):
        captured["iteration_kwargs"] = kwargs
        return 0

    exit_code = main(
        [
            "--dsn",
            "postgresql://user:pass@localhost:5432/taskplane",
            "--repo",
            "demo/taskplane",
            "--project-dir",
            str(tmp_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ],
        connect_fn=fake_connect,
        runtime_builder=fake_runtime_builder,
        supervisor_iteration=fake_iteration,
        sleep_fn=lambda seconds: None,
        run_once=True,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/taskplane"
    assert captured["runtime_connection"] is not None
    assert captured["iteration_kwargs"]["session_manager"] == "session-manager"
    assert captured["iteration_kwargs"]["wakeup_dispatcher"] == "wakeup-dispatcher"

