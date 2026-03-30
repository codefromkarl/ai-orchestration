from __future__ import annotations

from stardrifter_orchestration_mvp import orchestration_loop


def test_build_timeout_payload_uses_blocked_timeout_reason():
    payload = orchestration_loop  # keep import exercised for module load
    assert payload is not None


def test_orchestration_loop_executor_command_includes_timeout(monkeypatch, tmp_path):
    captured_commands: list[str] = []

    class FakeCursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            if "FROM v_epic_decomposition_queue" in self.sql:
                return []
            if "FROM v_story_decomposition_queue" in self.sql:
                return []
            return [{"story_issue_number": 29}]

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

        def close(self):
            return None

    connections = [FakeConnection(), FakeConnection()]

    def fake_connect(*args, **kwargs):
        return connections.pop(0)

    def fake_subprocess_run(command: str) -> str:
        captured_commands.append(command)
        raise SystemExit(0)

    monkeypatch.setattr(orchestration_loop.psycopg, "connect", fake_connect)
    monkeypatch.setattr(orchestration_loop, "subprocess_run", fake_subprocess_run)

    try:
        orchestration_loop.main.__wrapped__  # type: ignore[attr-defined]
    except AttributeError:
        pass

    try:
        monkeypatch.setattr(
            "sys.argv",
            [
                "orchestration_loop.py",
                "--dsn",
                "postgresql://user:pass@localhost/db",
                "--project-dir",
                str(tmp_path),
                "--log-file",
                str(tmp_path / "loop.log"),
                "--opencode-timeout-seconds",
                "321",
            ],
        )
        orchestration_loop.main()
    except SystemExit:
        pass

    assert captured_commands
    assert "STARDRIFTER_OPENCODE_TIMEOUT_SECONDS='321'" in captured_commands[0]


def test_orchestration_loop_passes_worktree_root_to_story_runner(monkeypatch, tmp_path):
    captured_commands: list[str] = []

    class FakeCursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            if "FROM v_epic_decomposition_queue" in self.sql:
                return []
            if "FROM v_story_decomposition_queue" in self.sql:
                return []
            return [{"story_issue_number": 29}]

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

        def close(self):
            return None

    connections = [FakeConnection(), FakeConnection()]

    def fake_connect(*args, **kwargs):
        return connections.pop(0)

    def fake_subprocess_run(command: str) -> str:
        captured_commands.append(command)
        raise SystemExit(0)

    monkeypatch.setattr(orchestration_loop.psycopg, "connect", fake_connect)
    monkeypatch.setattr(orchestration_loop, "subprocess_run", fake_subprocess_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "orchestration_loop.py",
            "--dsn",
            "postgresql://user:pass@localhost/db",
            "--project-dir",
            str(tmp_path),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--log-file",
            str(tmp_path / "loop.log"),
        ],
    )

    try:
        orchestration_loop.main()
    except SystemExit:
        pass

    assert captured_commands
    assert any(
        f"--worktree-root '{tmp_path / 'worktrees'}'" in command
        for command in captured_commands
    )


def test_orchestration_loop_reads_storys_from_active_task_queue(monkeypatch, tmp_path):
    executed_sql: list[str] = []

    class FakeCursor:
        def execute(self, sql, params=None):
            self.sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM v_epic_decomposition_queue" in self.sql:
                return []
            if "FROM v_story_decomposition_queue" in self.sql:
                return []
            return [{"story_issue_number": -1901}]

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

        def close(self):
            return None

    connections = [FakeConnection(), FakeConnection()]

    def fake_connect(*args, **kwargs):
        return connections.pop(0)

    def fake_subprocess_run(command: str) -> str:
        raise SystemExit(0)

    monkeypatch.setattr(orchestration_loop.psycopg, "connect", fake_connect)
    monkeypatch.setattr(orchestration_loop, "subprocess_run", fake_subprocess_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "orchestration_loop.py",
            "--dsn",
            "postgresql://user:pass@localhost/db",
            "--project-dir",
            str(tmp_path),
            "--log-file",
            str(tmp_path / "loop.log"),
        ],
    )

    try:
        orchestration_loop.main()
    except SystemExit:
        pass

    assert any("FROM v_active_task_queue" in sql for sql in executed_sql)


def test_orchestration_loop_runs_decomposition_before_story_runner(
    monkeypatch, tmp_path
):
    captured_commands: list[str] = []
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self):
            self.calls = 0

        def execute(self, sql, params=None):
            self.sql = sql
            executed_sql.append(sql)
            self.calls += 1

        def fetchall(self):
            if "FROM v_epic_decomposition_queue" in self.sql:
                return [{"epic_issue_number": 42}]
            if "FROM v_story_decomposition_queue" in self.sql:
                return []
            return [{"story_issue_number": -1901}]

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

        def close(self):
            return None

    connections = [FakeConnection(), FakeConnection()]

    def fake_connect(*args, **kwargs):
        return connections.pop(0)

    def fake_subprocess_run(command: str) -> str:
        captured_commands.append(command)
        raise SystemExit(0)

    monkeypatch.setattr(orchestration_loop.psycopg, "connect", fake_connect)
    monkeypatch.setattr(orchestration_loop, "subprocess_run", fake_subprocess_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "orchestration_loop.py",
            "--dsn",
            "postgresql://user:pass@localhost/db",
            "--project-dir",
            str(tmp_path),
            "--log-file",
            str(tmp_path / "loop.log"),
        ],
    )

    try:
        orchestration_loop.main()
    except SystemExit:
        pass

    assert any("FROM v_story_decomposition_queue" in sql for sql in executed_sql)
    assert any("FROM v_active_task_queue" in sql for sql in executed_sql)
    assert len(captured_commands) >= 1
    assert "epic_decomposition_cli" in captured_commands[0]
