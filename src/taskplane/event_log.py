from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import ExecutionCheckpoint, ExecutionSession

EVENT_TYPE_SESSION_CHECKPOINT = "session_checkpoint"
EVENT_TYPE_SESSION_RESUMED = "session_resumed"
EVENT_TYPE_RETRY_SCHEDULED = "retry_scheduled"
EVENT_TYPE_HUMAN_APPROVAL_REQUESTED = "human_approval_requested"
EVENT_TYPE_TASK_BLOCKED = "task_blocked"
EVENT_TYPE_TASK_FAILED = "task_failed"
EVENT_TYPE_TASK_COMPLETED = "task_completed"
EVENT_TYPE_TASK_STARTED = "task_started"
EVENT_TYPE_ARTIFACT_CREATED = "artifact_created"
EVENT_TYPE_EXECUTOR_SELECTED = "executor_selected"


@dataclass(frozen=True)
class EventEnvelope:
    category: str
    action: str
    work_id: str | None = None
    session_id: str | None = None
    run_id: int | None = None
    actor: str | None = None
    phase: str | None = None
    resolution: str | None = None
    summary: str | None = None
    wakeup_type: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_detail_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "action": self.action,
        }
        if self.phase is not None:
            payload["phase"] = self.phase
        if self.resolution is not None:
            payload["resolution"] = self.resolution
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.wakeup_type is not None:
            payload["wakeup_type"] = self.wakeup_type
        if self.actor is not None:
            payload["actor"] = self.actor
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        payload.update(self.detail)
        return payload


class EventLogRecorder(Protocol):
    def record(self, event: EventEnvelope) -> EventEnvelope | None: ...


@dataclass
class InMemoryEventLogRecorder:
    events: list[EventEnvelope] = field(default_factory=list)

    def record(self, event: EventEnvelope) -> EventEnvelope:
        self.events.append(event)
        return event


@dataclass
class PostgresEventLogRecorder:
    connection: Any

    def record(self, event: EventEnvelope) -> EventEnvelope:
        event_type = event_type_for_envelope(event)
        with self.connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_log (
                    event_type, work_id, run_id, session_id, actor, detail
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    event_type,
                    event.work_id,
                    event.run_id,
                    event.session_id,
                    event.actor,
                    event.to_detail_payload(),
                ),
            )
        return event


def event_type_for_envelope(event: EventEnvelope) -> str:
    if event.category == "session":
        if event.action == "checkpoint":
            return EVENT_TYPE_SESSION_CHECKPOINT
        if event.action in {"resumed", "resume"}:
            return EVENT_TYPE_SESSION_RESUMED
        if event.action == "completed":
            return EVENT_TYPE_TASK_COMPLETED
        if event.action == "failed":
            return EVENT_TYPE_TASK_FAILED
        if event.action == "blocked":
            return EVENT_TYPE_TASK_BLOCKED

    if event.category == "policy":
        if event.resolution == "retry_strategy":
            return EVENT_TYPE_RETRY_SCHEDULED
        if event.resolution == "auto_resolve":
            return EVENT_TYPE_TASK_BLOCKED
        if event.resolution == "human_required":
            return EVENT_TYPE_HUMAN_APPROVAL_REQUESTED
        if event.resolution == "failed_terminal":
            return EVENT_TYPE_TASK_FAILED
        if event.resolution == "blocked":
            return EVENT_TYPE_TASK_BLOCKED

    if event.category == "wakeup":
        if event.action in {"resumed", "resume"}:
            return EVENT_TYPE_SESSION_RESUMED
        raise ValueError(
            f"wakeup event action {event.action!r} is not persistable as a session resume"
        )

    raise ValueError(
        f"unsupported event envelope category={event.category!r} action={event.action!r}"
    )


def build_session_checkpoint_event(
    *,
    session: ExecutionSession,
    checkpoint: ExecutionCheckpoint,
    actor: str = "session_runtime_loop",
) -> EventEnvelope:
    return EventEnvelope(
        category="session",
        action="checkpoint",
        work_id=session.work_id,
        session_id=session.id,
        actor=actor,
        phase=checkpoint.phase,
        summary=checkpoint.summary,
        detail={
            "checkpoint_id": checkpoint.id,
            "checkpoint_phase_index": checkpoint.phase_index,
            "next_action_hint": checkpoint.next_action_hint,
            "session_status": session.status,
        },
    )


def build_policy_resolution_event(
    *,
    session: ExecutionSession,
    action: str,
    resolution: str,
    trigger_reason: str,
    applied: bool,
    phase: str | None = None,
    summary: str | None = None,
    actor: str = "session_runtime_loop",
    detail: dict[str, Any] | None = None,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "trigger_reason": trigger_reason,
        "applied": applied,
        "source": "session_runtime_loop",
    }
    if detail:
        payload.update(detail)
    return EventEnvelope(
        category="policy",
        action=action,
        work_id=session.work_id,
        session_id=session.id,
        actor=actor,
        phase=phase,
        resolution=resolution,
        summary=summary,
        detail=payload,
    )


def build_wakeup_event(
    *,
    session: ExecutionSession,
    action: str,
    wakeup_type: str | None = None,
    summary: str | None = None,
    actor: str = "session_runtime_loop",
    detail: dict[str, Any] | None = None,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "source": "session_runtime_loop",
    }
    if detail:
        payload.update(detail)
    return EventEnvelope(
        category="wakeup",
        action=action,
        work_id=session.work_id,
        session_id=session.id,
        actor=actor,
        summary=summary,
        wakeup_type=wakeup_type,
        detail=payload,
    )
