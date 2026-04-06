from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from taskplane.wakeup_dispatcher import PostgresWakeupDispatcher


class FakeCursor:
    def __init__(
        self,
        *,
        fetchone_results: list[Any] | None = None,
        fetchall_results: list[Any] | None = None,
        executed: list[tuple[str, tuple[Any, ...] | None]] | None = None,
    ) -> None:
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = executed if executed is not None else []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> Any | None:
        if not self.fetchone_results:
            return None
        return self.fetchone_results.pop(0)

    def fetchall(self) -> list[Any]:
        if not self.fetchall_results:
            return []
        return self.fetchall_results.pop(0)


class FakeConnection:
    def __init__(
        self,
        *,
        fetchone_results: list[Any] | None = None,
        fetchall_results: list[Any] | None = None,
    ) -> None:
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.commit_calls = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(
            fetchone_results=self.fetchone_results,
            fetchall_results=self.fetchall_results,
            executed=self.executed,
        )

    def commit(self) -> None:
        self.commit_calls += 1


def test_postgres_wakeup_dispatcher_registers_and_processes_fireable_rows() -> None:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    connection = FakeConnection(
        fetchone_results=[
            {
                "id": "wake-1",
                "session_id": "session-1",
                "work_id": "work-1",
                "wake_type": "timer",
                "wake_condition_json": {"wait_type": "timer"},
                "status": "pending",
                "scheduled_at": now,
                "fired_at": None,
                "created_at": now,
            },
            {
                "id": "wake-1",
                "session_id": "session-1",
                "work_id": "work-1",
                "wake_type": "timer",
                "wake_condition_json": {"wait_type": "timer"},
                "status": "fired",
                "scheduled_at": now,
                "fired_at": now,
                "created_at": now,
            },
        ],
        fetchall_results=[
            [
                {
                    "id": "wake-1",
                    "session_id": "session-1",
                    "work_id": "work-1",
                    "wake_type": "timer",
                    "wake_condition_json": {"wait_type": "timer"},
                    "status": "pending",
                    "scheduled_at": now,
                    "fired_at": None,
                    "created_at": now,
                }
            ]
        ],
    )
    dispatcher = PostgresWakeupDispatcher(connection)

    wakeup = dispatcher.register_wakeup(
        session_id="session-1",
        work_id="work-1",
        wake_type="timer",
        wake_condition={"wait_type": "timer"},
        scheduled_at="2026-04-05T00:00:00+00:00",
    )
    fired_session_ids = dispatcher.process_fireable()

    assert wakeup.id == "wake-1"
    assert fired_session_ids == ["session-1"]
    assert connection.commit_calls == 2
    assert "INSERT INTO execution_wakeup" in connection.executed[0][0]
    assert "FROM execution_wakeup" in connection.executed[1][0]
    assert "UPDATE execution_wakeup" in connection.executed[2][0]
