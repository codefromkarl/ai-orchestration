from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from taskplane.session_manager_postgres import PostgresSessionManager


class FakeCursor:
    def __init__(self, rows: list[Any], executed: list[tuple[str, tuple[Any, ...]]]):
        self._rows = rows
        self.executed = executed

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> Any | None:
        if not self._rows:
            return None
        return self._rows.pop(0)


class FakeConnection:
    def __init__(self, rows: list[Any]):
        self._rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows, self.executed)


class TestPostgresSessionManagerPolicyResolution:
    def test_create_session_and_checkpoint_ids_are_valid_uuid(self) -> None:
        conn = FakeConnection(rows=[(1,)])
        mgr = PostgresSessionManager(conn)

        session = mgr.create_session(work_id="work-1")
        checkpoint = mgr.append_checkpoint(
            session.id,
            phase="planning",
            summary="first checkpoint",
        )

        assert str(uuid.UUID(session.id)) == session.id
        assert checkpoint is not None
        assert str(uuid.UUID(checkpoint.id)) == checkpoint.id

    def test_record_and_fetch_latest_policy_resolution(self) -> None:
        created_at = datetime(2026, 4, 2, tzinfo=UTC)
        later_created_at = datetime(2026, 4, 2, 0, 1, tzinfo=UTC)
        conn = FakeConnection(
            [
                {
                    "id": "policy-1",
                    "session_id": "session-1",
                    "work_id": "work-1",
                    "risk_level": "medium",
                    "trigger_reason": "needs_decision with low attempt count",
                    "evidence_json": {"outcome": "needs_decision"},
                    "resolution": "retry_strategy",
                    "resolution_detail_json": {"strategy": "retry_with_narrowed_scope"},
                    "applied": True,
                    "created_at": created_at,
                },
                {
                    "id": "policy-2",
                    "session_id": "session-1",
                    "work_id": "work-1",
                    "risk_level": "high",
                    "trigger_reason": "needs_decision after multiple attempts",
                    "evidence_json": {"outcome": "needs_decision"},
                    "resolution": "human_required",
                    "resolution_detail_json": {"attempt_index": 5},
                    "applied": True,
                    "created_at": later_created_at,
                },
            ]
        )
        mgr = PostgresSessionManager(conn)

        record = mgr.record_policy_resolution(
            session_id="session-1",
            work_id="work-1",
            risk_level="medium",
            trigger_reason="needs_decision with low attempt count",
            evidence_json={"outcome": "needs_decision"},
            resolution="retry_strategy",
            resolution_detail_json={"strategy": "retry_with_narrowed_scope"},
            applied=True,
        )

        assert record is not None
        assert record.id == "policy-1"
        assert record.resolution == "retry_strategy"
        assert record.applied is True

        latest = mgr.get_latest_policy_resolution("session-1")
        assert latest is not None
        assert latest.id == "policy-2"
        assert latest.resolution == "human_required"
        assert latest.applied is True
        assert len(conn.executed) == 2
        assert "INSERT INTO policy_resolution" in conn.executed[0][0]
        assert "FROM policy_resolution" in conn.executed[1][0]

    def test_append_checkpoint_accepts_dict_row_for_phase_index(self) -> None:
        conn = FakeConnection(
            rows=[
                {"next_index": 1},
            ]
        )
        mgr = PostgresSessionManager(conn)

        session = mgr.create_session(work_id="work-1")
        checkpoint = mgr.append_checkpoint(
            session.id,
            phase="planning",
            summary="first checkpoint",
        )

        assert checkpoint is not None
        assert checkpoint.phase_index == 1
