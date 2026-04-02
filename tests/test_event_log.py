from __future__ import annotations

from typing import Any

import pytest

from taskplane.event_log import (
    EVENT_TYPE_SESSION_RESUMED,
    PostgresEventLogRecorder,
    build_policy_resolution_event,
    build_session_checkpoint_event,
    build_wakeup_event,
)
from taskplane.models import ExecutionCheckpoint, ExecutionSession


class FakeCursor:
    def __init__(self, executed: list[tuple[str, tuple[Any, ...]]]) -> None:
        self.executed = executed

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.executed.append((query, params))


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.executed)


@pytest.mark.parametrize(
    ("envelope", "expected_event_type"),
    [
        (
            build_session_checkpoint_event(
                session=ExecutionSession(
                    id="11111111-1111-1111-1111-111111111111",
                    work_id="work-1",
                    current_phase="researching",
                ),
                checkpoint=ExecutionCheckpoint(
                    id="22222222-2222-2222-2222-222222222222",
                    session_id="11111111-1111-1111-1111-111111111111",
                    phase="researching",
                    summary="Found modules",
                ),
            ),
            "session_checkpoint",
        ),
        (
            build_policy_resolution_event(
                session=ExecutionSession(
                    id="11111111-1111-1111-1111-111111111111",
                    work_id="work-1",
                    current_phase="planning",
                ),
                action="policy_retry",
                resolution="retry_strategy",
                trigger_reason="needs_decision with low attempt count",
                applied=True,
                phase="planning",
                summary="policy: retry",
                detail={"strategy": "retry_with_narrowed_scope"},
                ),
            "retry_scheduled",
        ),
        (
            build_policy_resolution_event(
                session=ExecutionSession(
                    id="11111111-1111-1111-1111-111111111111",
                    work_id="work-1",
                    current_phase="planning",
                ),
                action="auto_resolve",
                resolution="auto_resolve",
                trigger_reason="workspace cleanup",
                applied=True,
                phase="planning",
                summary="auto resolved",
                detail={"reason": "dirty workspace"},
            ),
            "task_blocked",
        ),
        (
            build_wakeup_event(
                session=ExecutionSession(
                    id="11111111-1111-1111-1111-111111111111",
                    work_id="work-1",
                    current_phase="planning",
                ),
                action="resumed",
                wakeup_type="timer",
                summary="session resumed",
                detail={"source": "process_session_wakeups"},
            ),
            EVENT_TYPE_SESSION_RESUMED,
        ),
    ],
)
def test_postgres_event_log_recorder_maps_envelope_to_insert(
    envelope: Any, expected_event_type: str
) -> None:
    conn = FakeConnection()
    recorder = PostgresEventLogRecorder(conn)

    returned = recorder.record(envelope)

    assert returned == envelope
    assert len(conn.executed) == 1
    query, params = conn.executed[0]
    assert "INSERT INTO event_log" in query
    assert params[0] == expected_event_type
    assert params[1] == "work-1"
    assert params[3] == "11111111-1111-1111-1111-111111111111"

    detail = params[5]
    assert detail["category"] == envelope.category
    assert detail["action"] == envelope.action
    if envelope.phase is not None:
        assert detail["phase"] == envelope.phase
    if envelope.resolution is not None:
        assert detail["resolution"] == envelope.resolution
    if envelope.summary is not None:
        assert detail["summary"] == envelope.summary
    if envelope.wakeup_type is not None:
        assert detail["wakeup_type"] == envelope.wakeup_type


def test_postgres_event_log_recorder_rejects_wakeup_fired() -> None:
    conn = FakeConnection()
    recorder = PostgresEventLogRecorder(conn)
    event = build_wakeup_event(
        session=ExecutionSession(
            id="11111111-1111-1111-1111-111111111111",
            work_id="work-1",
            current_phase="planning",
        ),
        action="fired",
        wakeup_type="timer",
        summary="wakeup fired",
        detail={"source": "fire_wakeup_for_event"},
    )

    with pytest.raises(ValueError):
        recorder.record(event)
