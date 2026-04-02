from __future__ import annotations

from dataclasses import dataclass


def test_session_cli_passes_resume_context_builder_to_runtime(monkeypatch, tmp_path, capsys):
    from taskplane import session_cli

    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    monkeypatch.setenv("TASKPLANE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.argv",
        [
            "stardrifter-session",
            "--work-id",
            "task-501",
            "--json-output",
        ],
    )

    captured: dict[str, object] = {}

    @dataclass(frozen=True)
    class FakeSession:
        id: str
        work_id: str
        current_phase: str = "researching"
        status: str = "completed"

    class FakeSessionManager:
        def __init__(self) -> None:
            self.session = FakeSession(id="session-1", work_id="task-501")

        def create_session(self, **kwargs):
            captured["create_session"] = kwargs
            return self.session

        def get_session(self, session_id: str):
            assert session_id == "session-1"
            return self.session

        def list_checkpoints(self, session_id: str):
            assert session_id == "session-1"
            return []

        def build_resume_context(self, session_id: str) -> str:
            assert session_id == "session-1"
            return "fallback session context"

    fake_manager = FakeSessionManager()

    monkeypatch.setattr(session_cli, "InMemorySessionManager", lambda: fake_manager)
    monkeypatch.setattr(
        session_cli,
        "_make_opencode_executor",
        lambda **kwargs: object(),
    )

    def fake_run_session_to_completion(**kwargs):
        captured["run_session_kwargs"] = kwargs
        return type(
            "Result",
            (),
            {"final_status": "completed", "iterations": 1},
        )()

    monkeypatch.setattr(
        session_cli,
        "run_session_to_completion",
        fake_run_session_to_completion,
    )

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")))

    exit_code = session_cli.main()

    assert exit_code == 0
    assert captured["create_session"] == {
        "work_id": "task-501",
        "current_phase": "researching",
        "context_summary": None,
    }
    run_kwargs = captured["run_session_kwargs"]
    assert run_kwargs["session_id"] == "session-1"
    assert run_kwargs["session_manager"] is fake_manager
    assert run_kwargs["resume_context_builder"] is not None
    assert capsys.readouterr().err.startswith(
        "Warning: PostgreSQL unavailable, using in-memory backend"
    )
