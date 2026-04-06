from __future__ import annotations

from taskplane.demo_cli import main


class _FakeCursor:
    def __init__(self, executed: list[tuple[str, tuple[object, ...] | None]]):
        self._executed = executed
        self._fetchone_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        self._executed.append((normalized, params))
        if "INSERT INTO github_issue_import_batch" in normalized:
            self._fetchone_result = (9001,)

    def fetchone(self):
        return self._fetchone_result


class _FakeConnection:
    def __init__(self):
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self.commit_called = 0

    def cursor(self):
        return _FakeCursor(self.executed)

    def commit(self):
        self.commit_called += 1

    def close(self):
        return None


def test_demo_seed_cli_inserts_demo_graph(monkeypatch, capsys):
    connection = _FakeConnection()
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/taskplane",
    )

    exit_code = main(
        ["seed", "--repo", "demo/taskplane"],
        connector=lambda dsn: connection,
    )

    assert exit_code == 0
    assert connection.commit_called == 1
    assert any("INSERT INTO github_issue_import_batch" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO github_issue_normalized" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO program_epic" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO program_story" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO work_item" in sql for sql, _ in connection.executed)
    assert "seeded demo repo demo/taskplane" in capsys.readouterr().out


def test_demo_seed_cli_resets_repo_before_insert_when_requested(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/taskplane",
    )

    exit_code = main(
        ["seed", "--repo", "demo/taskplane", "--reset"],
        connector=lambda dsn: connection,
    )

    assert exit_code == 0
    assert any("DELETE FROM github_issue_normalized WHERE repo = %s" in sql for sql, _ in connection.executed)
    assert any("DELETE FROM program_epic WHERE repo = %s" in sql for sql, _ in connection.executed)
