from pathlib import Path
from typing import Any

from taskplane.models import EpicRunResult
from taskplane.models import ProgramStory
from taskplane.scheduling_loop import (
    _pid_exists,
    run_supervisor_iteration,
)
from taskplane.repository import PostgresControlPlaneRepository


def test_run_supervisor_iteration_syncs_ready_states_before_scheduling(tmp_path):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: None,
    )

    assert launched == 0
    assert any("SELECT wi.id" in sql for sql in executed_sql)
    assert any("UPDATE work_item wi" in sql for sql in executed_sql)


def test_run_supervisor_iteration_can_inject_sync_ready_capability_without_building_scheduling_repository(
    tmp_path,
):
    sync_calls: list[object] = []

    class SyncOnlyRepository:
        def __init__(self, connection) -> None:
            self.connection = connection

        def sync_ready_states(self) -> None:
            sync_calls.append(self.connection)

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    connection = FakeConnection()

    launched = run_supervisor_iteration(
        connection=connection,
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=0,
        launcher=lambda command, log_path: None,
        ready_state_repository_builder=SyncOnlyRepository,
        repository_builder=lambda connection: (_ for _ in ()).throw(
            AssertionError("scheduling repository should not be constructed")
        ),
    )

    assert launched == 0
    assert sync_calls == [connection]


def test_run_supervisor_iteration_sync_ready_sql_guards_waiting_sessions(tmp_path):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: None,
    )

    executed = "\n".join(executed_sql)
    assert "FROM execution_session es" in executed
    assert "es.work_id = wi.id" in executed
    assert "es.status IN ('suspended', 'waiting_internal', 'waiting_external')" in executed


def test_run_supervisor_iteration_launches_decomposition_and_story_jobs(tmp_path):
    executed_sql: list[str] = []
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return [{"story_issue_number": 41}]
            if "FROM v_active_task_queue" in self.last_sql:
                return [
                    {
                        "work_id": "issue-69",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 69,
                        "task_type": "governance",
                        "blocking_mode": "hard",
                        "status": "ready",
                        "planned_paths": ["docs/baselines/wave0-freeze.md"],
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 2
    assert any("story_decomposition_cli" in command for command in launched_commands)
    assert any("--story-issue-number 42" in command for command in launched_commands)
    assert any("INSERT INTO execution_job" in sql for sql in executed_sql)


def test_run_supervisor_iteration_launches_story_completion_candidate(tmp_path):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "ps.execution_status NOT IN ('done', 'gated')" in self.last_sql:
                return [{"story_issue_number": 41}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 23456

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert any("--story-issue-number 41" in command for command in launched_commands)
    assert all(
        "story_decomposition_cli" not in command for command in launched_commands
    )


def test_run_supervisor_iteration_story_completion_query_excludes_gated_stories(
    tmp_path,
):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: None,
    )

    completion_sql = next(
        sql
        for sql in executed_sql
        if "SELECT" in sql
        and "FROM program_story ps" in sql
        and "story_issue_number" in sql
    )
    assert "ps.execution_status NOT IN ('done', 'gated')" in completion_sql


def test_run_supervisor_iteration_epic_iteration_query_excludes_gated_epics(tmp_path):
    launched_commands: list[str] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            return []

        def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
            return []

        def get_work_item(self, work_id: str) -> Any:
            return None

        def get_epic_execution_state(self, *, repo: str, epic_issue_number: int) -> Any:
            return None

        def upsert_epic_execution_state(self, state: Any) -> None:
            return None

        def record_operator_request(self, request: Any) -> int | None:
            return None

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""
            self.executed_sql: list[str] = []

        def execute(self, sql, params=None):
            self.last_sql = sql
            self.executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return []
            if "FROM program_epic" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            return None

    connection = FakeConnection()

    run_supervisor_iteration(
        connection=connection,
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: launched_commands.append(command),
    )

    epic_sql = next(
        sql
        for sql in connection.cursor_instance.executed_sql
        if "FROM program_epic" in sql
    )
    assert "execution_status NOT IN ('done', 'gated')" in epic_sql


def test_run_supervisor_iteration_launches_lane_08_epic_decomposition_job(tmp_path):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return [{"epic_issue_number": 63}]
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_epic" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 63008

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert any("epic_decomposition_cli" in command for command in launched_commands)
    assert any("--epic-issue-number 63" in command for command in launched_commands)


def test_run_supervisor_iteration_reconciles_finished_jobs(tmp_path):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return [
                    {
                        "id": 1,
                        "pid": 999,
                        "status": "running",
                    }
                ]
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FinishedProcess:
        pid = 999

        def poll(self):
            return 0

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        running_processes={999: FinishedProcess()},
        launcher=lambda command, log_path: FinishedProcess(),
    )

    assert launched == 0
    assert any("UPDATE execution_job" in sql for sql in executed_sql)


def test_run_supervisor_iteration_reconciles_finished_jobs_without_in_memory_process(
    tmp_path,
):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            executed_sql.append(sql)

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return [
                    {
                        "id": 1,
                        "pid": 999,
                        "status": "running",
                        "work_id": "issue-69",
                        "story_issue_number": None,
                    }
                ]
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def fetchone(self):
            if "FROM work_item" in self.last_sql:
                return {"status": "done"}
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        running_processes={},
        launcher=lambda command, log_path: None,
        pid_exists=lambda pid: False,
    )

    assert launched == 0
    assert any("UPDATE execution_job" in sql for sql in executed_sql)


def test_run_supervisor_iteration_prioritizes_low_conflict_tasks(tmp_path):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if self.last_sql.lstrip().startswith("SELECT wi.id"):
                return []
            if "FROM work_dependency" in self.last_sql:
                return [
                    {
                        "work_id": "issue-71",
                        "depends_on_work_id": "issue-70",
                        "dependency_status": "ready",
                        "dependency_blocking_mode": "soft",
                    }
                ]
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return [
                    {
                        "work_id": "issue-69",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 69,
                        "task_type": "governance",
                        "blocking_mode": "hard",
                        "status": "ready",
                        "planned_paths": ["docs/baselines/wave0-freeze.md"],
                    },
                    {
                        "work_id": "issue-70",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 70,
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "status": "ready",
                        "planned_paths": ["docs/domains/*/starsector-reference.md"],
                    },
                    {
                        "work_id": "issue-71",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 71,
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "status": "ready",
                        "planned_paths": [
                            "docs/domains/*/README.md",
                            "docs/domains/*/execution-plan.md",
                        ],
                    },
                    {
                        "work_id": "issue-72",
                        "canonical_story_issue_number": 43,
                        "source_issue_number": 72,
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "status": "ready",
                        "planned_paths": [
                            "docs/project/design/",
                            "docs/project/boundaries/",
                        ],
                    },
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    pid_counter = iter([1001, 1002])

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess(next(pid_counter))
        ),
    )

    assert launched == 2
    assert "--story-issue-number 42" in launched_commands[0]
    assert "--story-issue-number 43" in launched_commands[1]


def test_run_supervisor_iteration_traces_dependencies_to_root_tasks(tmp_path):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if self.last_sql.lstrip().startswith("SELECT wi.id"):
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return [
                    {
                        "work_id": "issue-71",
                        "depends_on_work_id": "issue-70",
                        "dependency_status": "pending",
                        "dependency_blocking_mode": "hard",
                    }
                ]
            if "FROM v_active_task_queue" in self.last_sql:
                return [
                    {
                        "work_id": "issue-70",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 70,
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "status": "ready",
                        "planned_paths": ["docs/domains/*/starsector-reference.md"],
                    },
                    {
                        "work_id": "issue-71",
                        "canonical_story_issue_number": 42,
                        "source_issue_number": 71,
                        "task_type": "documentation",
                        "blocking_mode": "hard",
                        "status": "ready",
                        "planned_paths": ["docs/domains/*/README.md"],
                    },
                    {
                        "work_id": "issue-72",
                        "canonical_story_issue_number": 43,
                        "source_issue_number": 72,
                        "task_type": "documentation",
                        "blocking_mode": "soft",
                        "status": "ready",
                        "planned_paths": ["docs/project/design/"],
                    },
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    pid_counter = iter([2001, 2002])

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess(next(pid_counter))
        ),
    )

    assert launched == 2
    assert any("--story-issue-number 42" in command for command in launched_commands)
    assert any("--story-issue-number 43" in command for command in launched_commands)


def test_run_supervisor_iteration_launches_story_completion_pass_for_terminal_story(
    tmp_path,
):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [{"story_issue_number": 42}]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert any("--story-issue-number 42" in command for command in launched_commands)


def test_run_supervisor_iteration_uses_epic_aware_story_selection_for_story_workers(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []
    listed_epics: list[int] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            listed_epics.append(epic_issue_number)
            if epic_issue_number == 11:
                return [
                    ProgramStory(
                        issue_number=41,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 41",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                    ProgramStory(
                        issue_number=42,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 42",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                ]
            if epic_issue_number == 12:
                return [
                    ProgramStory(
                        issue_number=51,
                        repo=repo,
                        epic_issue_number=12,
                        title="Story 51",
                        lane="Lane 02",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    )
                ]
            return []

    monkeypatch.setattr(
        "taskplane.repository.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_select_story_batch(*, stories, repository, max_batch_size=1):
        assert max_batch_size == 1
        return [stories[-1]] if stories else []

    monkeypatch.setattr(
        "taskplane.epic_scheduler.select_story_batch",
        fake_select_story_batch,
    )
    # Also patch the import in schedulers.story_scheduler which re-exports from epic_scheduler
    monkeypatch.setattr(
        "taskplane.schedulers.story_scheduler.select_story_batch",
        fake_select_story_batch,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [
                    {"story_issue_number": 41, "epic_issue_number": 11},
                    {"story_issue_number": 42, "epic_issue_number": 11},
                    {"story_issue_number": 51, "epic_issue_number": 12},
                ]
            if "FROM program_epic" in self.last_sql:
                return [
                    {"epic_issue_number": 11},
                    {"epic_issue_number": 12},
                ]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    pid_counter = iter([5101, 5102])

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess(next(pid_counter))
        ),
    )

    assert launched == 2
    assert listed_epics[:2] == [11, 12]
    assert any("--story-issue-number 42" in command for command in launched_commands)
    assert any("--story-issue-number 51" in command for command in launched_commands)
    assert all(
        "--story-issue-number 41" not in command for command in launched_commands
    )


def test_run_supervisor_iteration_passes_story_active_wave_to_story_worker(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            if epic_issue_number == 17:
                return [
                    ProgramStory(
                        issue_number=169,
                        repo=repo,
                        epic_issue_number=17,
                        title="Story 169",
                        lane="Lane 05",
                        complexity="high",
                        program_status="approved",
                        execution_status="active",
                        active_wave="wave-4",
                    )
                ]
            return []

    monkeypatch.setattr(
        "taskplane.repository.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_select_story_batch(*, stories, repository, max_batch_size=1):
        return stories[:1]

    monkeypatch.setattr(
        "taskplane.epic_scheduler.select_story_batch",
        fake_select_story_batch,
    )
    monkeypatch.setattr(
        "taskplane.schedulers.story_scheduler.select_story_batch",
        fake_select_story_batch,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [{"story_issue_number": 169, "epic_issue_number": 17}]
            if "FROM program_epic" in self.last_sql:
                return [{"epic_issue_number": 17}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 5517

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert any("--story-issue-number 169" in command for command in launched_commands)
    assert any("--allowed-wave wave-4" in command for command in launched_commands)


def test_run_supervisor_iteration_defaults_story_selection_to_one_per_epic(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            return [
                ProgramStory(
                    issue_number=41,
                    repo=repo,
                    epic_issue_number=11,
                    title="Story 41",
                    lane="Lane 01",
                    complexity="medium",
                    program_status="approved",
                    execution_status="active",
                ),
                ProgramStory(
                    issue_number=42,
                    repo=repo,
                    epic_issue_number=11,
                    title="Story 42",
                    lane="Lane 01",
                    complexity="medium",
                    program_status="approved",
                    execution_status="active",
                ),
            ]

    monkeypatch.setattr(
        "taskplane.repository.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_select_story_batch(*, stories, repository, max_batch_size=1):
        assert max_batch_size == 1
        return stories[:1]

    monkeypatch.setattr(
        "taskplane.epic_scheduler.select_story_batch",
        fake_select_story_batch,
    )
    # Also patch the import in schedulers.story_scheduler which re-exports from epic_scheduler
    monkeypatch.setattr(
        "taskplane.schedulers.story_scheduler.select_story_batch",
        fake_select_story_batch,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM execution_session es" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [
                    {"story_issue_number": 41, "epic_issue_number": 11},
                    {"story_issue_number": 42, "epic_issue_number": 11},
                ]
            if "FROM program_epic" in self.last_sql:
                return [{"epic_issue_number": 11}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 6101

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=3,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert launched_commands == [launched_commands[0]]
    assert "--story-issue-number 41" in launched_commands[0]


def test_run_supervisor_iteration_allows_configured_multi_story_batch_per_epic(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []
    observed_batch_sizes: list[int] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            return [
                ProgramStory(
                    issue_number=41,
                    repo=repo,
                    epic_issue_number=11,
                    title="Story 41",
                    lane="Lane 01",
                    complexity="medium",
                    program_status="approved",
                    execution_status="active",
                ),
                ProgramStory(
                    issue_number=42,
                    repo=repo,
                    epic_issue_number=11,
                    title="Story 42",
                    lane="Lane 01",
                    complexity="medium",
                    program_status="approved",
                    execution_status="active",
                ),
                ProgramStory(
                    issue_number=43,
                    repo=repo,
                    epic_issue_number=11,
                    title="Story 43",
                    lane="Lane 01",
                    complexity="medium",
                    program_status="approved",
                    execution_status="active",
                ),
            ]

    monkeypatch.setattr(
        "taskplane.repository.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_select_story_batch(*, stories, repository, max_batch_size=1):
        observed_batch_sizes.append(max_batch_size)
        return stories[:max_batch_size]

    monkeypatch.setattr(
        "taskplane.epic_scheduler.select_story_batch",
        fake_select_story_batch,
    )
    # Also patch the import in schedulers.story_scheduler which re-exports from epic_scheduler
    monkeypatch.setattr(
        "taskplane.schedulers.story_scheduler.select_story_batch",
        fake_select_story_batch,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [
                    {"story_issue_number": 41, "epic_issue_number": 11},
                    {"story_issue_number": 42, "epic_issue_number": 11},
                    {"story_issue_number": 43, "epic_issue_number": 11},
                ]
            if "FROM program_epic" in self.last_sql:
                return [{"epic_issue_number": 11}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    pid_counter = iter([7101, 7102])

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        epic_story_batch_size=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess(next(pid_counter))
        ),
    )

    assert launched == 2
    assert observed_batch_sizes == [2]
    assert any("--story-issue-number 41" in command for command in launched_commands)
    assert any("--story-issue-number 42" in command for command in launched_commands)
    assert all(
        "--story-issue-number 43" not in command for command in launched_commands
    )


def test_run_supervisor_iteration_records_epic_story_job_metadata(tmp_path):
    insert_params: list[tuple[object, ...]] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql
            if "INSERT INTO execution_job" in sql and params is not None:
                insert_params.append(tuple(params))

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [{"story_issue_number": 41, "epic_issue_number": 11}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 8101

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: FakeProcess(),
    )

    assert launched == 1
    assert len(insert_params) == 1
    assert insert_params[0][:5] == (
        "codefromkarl/stardrifter",
        "story_worker",
        41,
        11,
        "supervisor",
    )


def test_run_supervisor_iteration_prefers_epic_iteration_story_selection_over_completion_queue(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []
    iterated_epics: list[int] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            if epic_issue_number == 11:
                return [
                    ProgramStory(
                        issue_number=42,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 42",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                    ProgramStory(
                        issue_number=43,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 43",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                ]
            return []

        def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
            return []

        def get_work_item(self, work_id: str) -> Any:
            return None

        def get_epic_execution_state(self, *, repo: str, epic_issue_number: int) -> Any:
            return None

        def upsert_epic_execution_state(self, state: Any) -> None:
            return None

        def record_operator_request(self, request: Any) -> int | None:
            return None

    monkeypatch.setattr(
        "taskplane.scheduling_loop.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_select_story_batch(*, stories, repository, max_batch_size=1):
        # Return all stories up to max_batch_size
        return stories[:max_batch_size]

    monkeypatch.setattr(
        "taskplane.epic_scheduler.select_story_batch",
        fake_select_story_batch,
    )
    monkeypatch.setattr(
        "taskplane.schedulers.story_scheduler.select_story_batch",
        fake_select_story_batch,
    )

    def fake_run_epic_iteration(
        *,
        repo: str,
        epic_issue_number: int,
        repository,
        story_runner,
        story_batch_selector,
        max_parallel_stories: int,
        **kwargs,
    ):
        iterated_epics.append(epic_issue_number)
        # Just return a result that indicates stories were selected
        # The actual story selection happens via story_batch_selector in preview
        return EpicRunResult(
            epic_issue_number=epic_issue_number,
            completed_story_issue_numbers=[],
            blocked_story_issue_numbers=[],
            remaining_story_issue_numbers=[42, 43] if epic_issue_number == 11 else [],
            epic_complete=False,
            reason_code="epic_incomplete",
        )

    monkeypatch.setattr(
        "taskplane.epic_runner.run_epic_iteration",
        fake_run_epic_iteration,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [
                    {"story_issue_number": 42, "epic_issue_number": 11},
                    {"story_issue_number": 43, "epic_issue_number": 11},
                ]
            if "FROM program_epic" in self.last_sql:
                return [{"epic_issue_number": 11}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    pid_counter = iter([9101, 9102])

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=2,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess(next(pid_counter))
        ),
    )

    assert launched == 2
    assert iterated_epics == [11]
    assert any("--story-issue-number 42" in command for command in launched_commands)
    assert any("--story-issue-number 43" in command for command in launched_commands)


def test_run_supervisor_iteration_prefers_resumable_story_before_completion_candidate(
    tmp_path,
):
    launched_commands: list[str] = []

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM execution_session es" in self.last_sql:
                return [{"story_issue_number": 132, "epic_issue_number": 64}]
            if "ps.execution_status NOT IN ('done', 'gated')" in self.last_sql:
                return [{"story_issue_number": -1901, "epic_issue_number": 19}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            if "epic_issue_number = %s" in self.last_sql:
                return [
                    {
                        "issue_number": 132,
                        "repo": "codefromkarl/stardrifter",
                        "epic_issue_number": 64,
                        "title": "Story 132",
                        "lane": "Lane 09",
                        "complexity": "medium",
                        "program_status": "approved",
                        "execution_status": "active",
                        "active_wave": "Wave0",
                        "notes": None,
                    }
                ]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 9201

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert len(launched_commands) == 1
    assert "--story-issue-number 132" in launched_commands[0]
    assert "--story-issue-number -1901" not in launched_commands[0]


def test_run_supervisor_iteration_keeps_story_completion_candidate_fallback_when_epic_iteration_selects_nothing(
    tmp_path,
    monkeypatch,
):
    launched_commands: list[str] = []

    class FakeRepository:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.story_dependencies = []

        def sync_ready_states(self) -> None:
            return None

        def list_program_stories_for_epic(self, *, repo: str, epic_issue_number: int):
            if epic_issue_number == 11:
                return [
                    ProgramStory(
                        issue_number=42,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 42",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                    ProgramStory(
                        issue_number=43,
                        repo=repo,
                        epic_issue_number=11,
                        title="Story 43",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="active",
                    ),
                ]
            return []

        def list_story_work_item_ids(self, story_issue_number: int) -> list[str]:
            return []

        def get_work_item(self, work_id: str) -> Any:
            return None

        def get_epic_execution_state(self, *, repo: str, epic_issue_number: int) -> Any:
            return None

        def upsert_epic_execution_state(self, state: Any) -> None:
            return None

        def record_operator_request(self, request: Any) -> int | None:
            return None

    monkeypatch.setattr(
        "taskplane.scheduling_loop.PostgresControlPlaneRepository",
        FakeRepository,
    )

    def fake_run_epic_iteration(
        *,
        repo: str,
        epic_issue_number: int,
        repository,
        story_runner,
        story_batch_selector,
        max_parallel_stories: int,
        **kwargs,
    ):
        del (
            repo,
            epic_issue_number,
            repository,
            story_runner,
            story_batch_selector,
            max_parallel_stories,
            kwargs,
        )
        return EpicRunResult(
            epic_issue_number=11,
            completed_story_issue_numbers=[],
            blocked_story_issue_numbers=[],
            remaining_story_issue_numbers=[],
            epic_complete=False,
            reason_code="no_batch_safe_stories_available",
        )

    monkeypatch.setattr(
        "taskplane.epic_runner.run_epic_iteration",
        fake_run_epic_iteration,
    )

    class FakeCursor:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, sql, params=None):
            self.last_sql = sql

        def fetchall(self):
            if "FROM execution_job" in self.last_sql:
                return []
            if "FROM work_claim" in self.last_sql:
                return []
            if "FROM work_dependency" in self.last_sql:
                return []
            if "FROM v_epic_decomposition_queue" in self.last_sql:
                return []
            if "FROM v_story_decomposition_queue" in self.last_sql:
                return []
            if "FROM program_story ps" in self.last_sql:
                return [{"story_issue_number": 41, "epic_issue_number": 11}]
            if "FROM v_active_task_queue" in self.last_sql:
                return []
            if "FROM program_epic" in self.last_sql:
                return [{"epic_issue_number": 11}]
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    class FakeProcess:
        pid = 9201

        def poll(self):
            return None

    launched = run_supervisor_iteration(
        connection=FakeConnection(),
        repo="codefromkarl/stardrifter",
        dsn="postgresql://user:pass@localhost/db",
        project_dir=tmp_path,
        log_dir=tmp_path / "logs",
        worktree_root=tmp_path / "worktrees",
        max_parallel_jobs=1,
        launcher=lambda command, log_path: (
            launched_commands.append(command) or FakeProcess()
        ),
    )

    assert launched == 1
    assert launched_commands == [launched_commands[0]]
    assert "--story-issue-number 41" in launched_commands[0]


def test_pid_exists_treats_zombie_process_as_missing(monkeypatch):
    zombie_status = "Name:\tpython3\nState:\tZ (zombie)\n"

    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda self: zombie_status if str(self).endswith("/status") else "",
    )

    assert _pid_exists(12345) is False
