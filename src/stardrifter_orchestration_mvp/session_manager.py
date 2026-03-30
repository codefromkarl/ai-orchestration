from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from .models import (
    SESSION_TERMINAL_STATUSES,
    SESSION_WAITING_STATUSES,
    ExecutionCheckpoint,
    ExecutionSession,
    SessionStatus,
)


def _generate_id() -> str:
    return secrets.token_hex(16)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InMemorySessionManager:
    sessions_by_id: dict[str, ExecutionSession] = field(default_factory=dict)
    checkpoints_by_session_id: dict[str, list[ExecutionCheckpoint]] = field(
        default_factory=dict
    )
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def create_session(
        self,
        *,
        work_id: str,
        current_phase: str = "planning",
        strategy_name: str | None = None,
        context_summary: str | None = None,
        attempt_index: int = 1,
        parent_session_id: str | None = None,
    ) -> ExecutionSession:
        session_id = _generate_id()
        now = _now_iso()
        session = ExecutionSession(
            id=session_id,
            work_id=work_id,
            status="active",
            attempt_index=attempt_index,
            parent_session_id=parent_session_id,
            current_phase=current_phase,
            strategy_name=strategy_name,
            context_summary=context_summary,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.sessions_by_id[session_id] = session
            self.checkpoints_by_session_id[session_id] = []
        return session

    def get_session(self, session_id: str) -> ExecutionSession | None:
        return self.sessions_by_id.get(session_id)

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
    ) -> ExecutionSession | None:
        with self._lock:
            session = self.sessions_by_id.get(session_id)
            if session is None:
                return None
            updated = replace(session, status=status, updated_at=_now_iso())
            self.sessions_by_id[session_id] = updated
            return updated

    def suspend_session(
        self,
        session_id: str,
        waiting_reason: str,
        wake_after: str | None = None,
        wake_condition: dict[str, Any] | None = None,
    ) -> ExecutionSession | None:
        with self._lock:
            session = self.sessions_by_id.get(session_id)
            if session is None:
                return None
            updated = replace(
                session,
                status="suspended",
                waiting_reason=waiting_reason,
                wake_after=wake_after,
                wake_condition=wake_condition,
                updated_at=_now_iso(),
            )
            self.sessions_by_id[session_id] = updated
            return updated

    def resume_session(self, session_id: str) -> ExecutionSession | None:
        with self._lock:
            session = self.sessions_by_id.get(session_id)
            if session is None:
                return None
            if session.status not in SESSION_WAITING_STATUSES:
                return session
            updated = replace(
                session,
                status="active",
                waiting_reason=None,
                wake_after=None,
                wake_condition=None,
                updated_at=_now_iso(),
            )
            self.sessions_by_id[session_id] = updated
            return updated

    def update_session_phase(
        self,
        session_id: str,
        phase: str,
        strategy_name: str | None = None,
    ) -> ExecutionSession | None:
        with self._lock:
            session = self.sessions_by_id.get(session_id)
            if session is None:
                return None
            updates: dict[str, Any] = {
                "current_phase": phase,
                "updated_at": _now_iso(),
            }
            if strategy_name is not None:
                updates["strategy_name"] = strategy_name
            updated = replace(session, **updates)
            self.sessions_by_id[session_id] = updated
            return updated

    def append_checkpoint(
        self,
        session_id: str,
        *,
        phase: str,
        summary: str,
        artifacts: dict[str, Any] | None = None,
        tool_state: dict[str, Any] | None = None,
        subtasks: list[Any] | None = None,
        failure_context: dict[str, Any] | None = None,
        next_action_hint: str | None = None,
        next_action_params: dict[str, Any] | None = None,
    ) -> ExecutionCheckpoint | None:
        with self._lock:
            if session_id not in self.sessions_by_id:
                return None
            checkpoints = self.checkpoints_by_session_id.get(session_id, [])
            phase_index = sum(1 for c in checkpoints if c.phase == phase) + 1
            ckpt_id = _generate_id()
            ckpt = ExecutionCheckpoint(
                id=ckpt_id,
                session_id=session_id,
                phase=phase,
                phase_index=phase_index,
                summary=summary,
                artifacts=artifacts,
                tool_state=tool_state,
                subtasks=subtasks,
                failure_context=failure_context,
                next_action_hint=next_action_hint,
                next_action_params=next_action_params,
                created_at=_now_iso(),
            )
            checkpoints.append(ckpt)
            self.checkpoints_by_session_id[session_id] = checkpoints
            session = self.sessions_by_id[session_id]
            self.sessions_by_id[session_id] = replace(
                session,
                last_checkpoint_id=ckpt_id,
                updated_at=_now_iso(),
            )
            return ckpt

    def get_latest_checkpoint(self, session_id: str) -> ExecutionCheckpoint | None:
        checkpoints = self.checkpoints_by_session_id.get(session_id, [])
        return checkpoints[-1] if checkpoints else None

    def list_checkpoints(self, session_id: str) -> list[ExecutionCheckpoint]:
        return list(self.checkpoints_by_session_id.get(session_id, []))

    def build_resume_context(self, session_id: str) -> str:
        session = self.get_session(session_id)
        if session is None:
            return ""
        parts: list[str] = []
        if session.context_summary:
            parts.append(f"Context: {session.context_summary}")
        if session.strategy_name:
            parts.append(f"Strategy: {session.strategy_name}")
        checkpoints = self.checkpoints_by_session_id.get(session_id, [])
        if checkpoints:
            last_ckpt = checkpoints[-1]
            parts.append(
                f"Last phase: {last_ckpt.phase} (index {last_ckpt.phase_index})"
            )
            parts.append(f"Last summary: {last_ckpt.summary}")
            if last_ckpt.next_action_hint:
                parts.append(f"Next action: {last_ckpt.next_action_hint}")
            if last_ckpt.artifacts:
                parts.append(
                    f"Artifacts: {json.dumps(last_ckpt.artifacts, ensure_ascii=False)}"
                )
        return "\n".join(parts)

    def list_active_sessions_for_work(self, work_id: str) -> list[ExecutionSession]:
        return [
            s
            for s in self.sessions_by_id.values()
            if s.work_id == work_id and s.status not in SESSION_TERMINAL_STATUSES
        ]

    def list_wakeable_sessions(self) -> list[ExecutionSession]:
        now = _now_iso()
        result: list[ExecutionSession] = []
        for session in self.sessions_by_id.values():
            if session.status not in SESSION_WAITING_STATUSES:
                continue
            if session.wake_after is not None and session.wake_after <= now:
                result.append(session)
        return result

    def list_all_sessions(self) -> list[ExecutionSession]:
        return list(self.sessions_by_id.values())

    def list_timed_out_sessions(
        self, *, max_age_seconds: int = 86400
    ) -> list[ExecutionSession]:
        now = datetime.now(UTC)
        result: list[ExecutionSession] = []
        for session in self.sessions_by_id.values():
            if session.status in SESSION_TERMINAL_STATUSES:
                continue
            if session.created_at is None:
                continue
            try:
                created = datetime.fromisoformat(session.created_at)
                age = (now - created).total_seconds()
                if age > max_age_seconds:
                    result.append(session)
            except (ValueError, TypeError):
                pass
        return result

    def abandon_timed_out_sessions(self, *, max_age_seconds: int = 86400) -> list[str]:
        timed_out = self.list_timed_out_sessions(max_age_seconds=max_age_seconds)
        abandoned_ids: list[str] = []
        for session in timed_out:
            updated = replace(
                session,
                status="failed_terminal",
                waiting_reason="timeout",
                updated_at=_now_iso(),
            )
            with self._lock:
                self.sessions_by_id[session.id] = updated
            self.append_checkpoint(
                session.id,
                phase=session.current_phase,
                summary=f"session abandoned: exceeded {max_age_seconds}s lifetime",
                failure_context={"max_age_seconds": max_age_seconds},
                next_action_hint="restart",
            )
            abandoned_ids.append(session.id)
        return abandoned_ids
