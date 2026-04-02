from unittest.mock import MagicMock, patch

from taskplane.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterRecord,
)


def test_dlq_move_to_dlq():
    with patch(
        "taskplane.dead_letter_queue.psycopg.connect"
    ) as mock_connect:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = {"id": 1, "moved_at": "2026-01-01T00:00:00"}
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_connect.return_value = mock_conn

        dlq = DeadLetterQueue(dsn="postgresql://fake:fake@localhost/fake")
        record = dlq.move_to_dlq(
            work_id="task-123",
            original_status="pending",
            failure_reason="timeout",
            attempt_count=5,
            last_run_id=42,
            moved_by="test-worker",
        )

        assert record.id == 1
        assert record.work_id == "task-123"
        assert record.failure_reason == "timeout"
        assert record.attempt_count == 5


def test_dlq_resolve():
    with patch(
        "taskplane.dead_letter_queue.psycopg.connect"
    ) as mock_connect:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_connect.return_value = mock_conn

        dlq = DeadLetterQueue(dsn="postgresql://fake:fake@localhost/fake")
        result = dlq.resolve(dlq_id=1, resolution="human_resolve", resolved_by="admin")

        assert result is True


def test_dlq_list_unresolved():
    with patch(
        "taskplane.dead_letter_queue.psycopg.connect"
    ) as mock_connect:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "work_id": "task-123",
                "original_status": "pending",
                "failure_reason": "timeout",
                "attempt_count": 5,
                "last_run_id": 42,
                "moved_at": "2026-01-01T00:00:00",
                "moved_by": "system",
                "resolution": None,
                "resolved_at": None,
                "resolved_by": None,
            }
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_connect.return_value = mock_conn

        dlq = DeadLetterQueue(dsn="postgresql://fake:fake@localhost/fake")
        records = dlq.list_unresolved()

        assert len(records) == 1
        assert records[0].work_id == "task-123"
        assert records[0].resolution is None


def test_dead_letter_record_is_immutable():
    record = DeadLetterRecord(
        id=1,
        work_id="task-123",
        original_status="pending",
        failure_reason="timeout",
        attempt_count=5,
        last_run_id=42,
        moved_at="2026-01-01",
        moved_by="system",
    )
    assert record.work_id == "task-123"
    assert record.failure_reason == "timeout"
