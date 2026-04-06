"""PostgreSQL implementation of session manager."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .models import (
    SESSION_TERMINAL_STATUSES,
    SESSION_WAITING_STATUSES,
    ExecutionCheckpoint,
    ExecutionSession,
    PolicyResolutionRecord,
    SessionStatus,
)


def _generate_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_session(row: Any) -> ExecutionSession:
    def _val(key: str) -> Any:
        if hasattr(row, key):
            return getattr(row, key)
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return None

    wake_condition = _val("wake_condition_json")
    if isinstance(wake_condition, str):
        try:
            wake_condition = json.loads(wake_condition)
        except (json.JSONDecodeError, TypeError):
            wake_condition = None

    return ExecutionSession(
        id=str(_val("id")),
        work_id=str(_val("work_id")),
        status=str(_val("status") or "active"),
        attempt_index=int(_val("attempt_index") or 1),
        parent_session_id=_val("parent_session_id"),
        current_phase=str(_val("current_phase") or "planning"),
        strategy_name=_val("strategy_name"),
        resume_token=_val("resume_token"),
        waiting_reason=_val("waiting_reason"),
        wake_after=_val("wake_after").isoformat() if _val("wake_after") else None,
        wake_condition=wake_condition,
        context_summary=_val("context_summary"),
        last_checkpoint_id=_val("last_checkpoint_id"),
        created_at=_val("created_at").isoformat() if _val("created_at") else None,
        last_heartbeat_at=_val("last_heartbeat_at").isoformat()
        if _val("last_heartbeat_at")
        else None,
        updated_at=_val("updated_at").isoformat() if _val("updated_at") else None,
    )


def _row_to_checkpoint(row: Any) -> ExecutionCheckpoint:
    def _val(key: str) -> Any:
        if hasattr(row, key):
            return getattr(row, key)
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return None

    def _json_val(key: str) -> Any:
        v = _val(key)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    return ExecutionCheckpoint(
        id=str(_val("id")),
        session_id=str(_val("session_id")),
        phase=str(_val("phase")),
        phase_index=int(_val("phase_index") or 1),
        summary=str(_val("summary") or ""),
        artifacts=_json_val("artifacts_json"),
        tool_state=_json_val("tool_state_json"),
        subtasks=_json_val("subtasks_json"),
        failure_context=_json_val("failure_context_json"),
        next_action_hint=_val("next_action_hint"),
        next_action_params=_json_val("next_action_params_json"),
        created_at=_val("created_at").isoformat() if _val("created_at") else None,
    )


def _row_to_policy_resolution(row: Any) -> PolicyResolutionRecord:
    def _val(key: str) -> Any:
        if hasattr(row, key):
            return getattr(row, key)
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return None

    def _json_val(key: str) -> Any:
        v = _val(key)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    created_at = _val("created_at")
    identifier = _val("id")
    return PolicyResolutionRecord(
        id=str(identifier) if identifier is not None else None,
        session_id=str(_val("session_id")),
        work_id=str(_val("work_id")),
        risk_level=str(_val("risk_level") or ""),
        trigger_reason=str(_val("trigger_reason") or ""),
        evidence_json=_json_val("evidence_json"),
        resolution=str(_val("resolution") or ""),
        resolution_detail_json=_json_val("resolution_detail_json"),
        applied=bool(_val("applied")),
        created_at=created_at.isoformat() if created_at else None,
    )


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


class PostgresSessionManager:
    """PostgreSQL-backed session manager."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _commit(self) -> None:
        commit = getattr(self._connection, "commit", None)
        if callable(commit):
            commit()

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
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_session
                    (id, work_id, status, attempt_index, parent_session_id,
                     current_phase, strategy_name, context_summary,
                     created_at, updated_at)
                VALUES (%s, %s, 'active', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    work_id,
                    attempt_index,
                    parent_session_id,
                    current_phase,
                    strategy_name,
                    context_summary,
                    now,
                    now,
                ),
            )
        self._commit()
        return ExecutionSession(
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

    def get_session(self, session_id: str) -> ExecutionSession | None:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT * FROM execution_session WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_session(row)

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
    ) -> ExecutionSession | None:
        now = _now_iso()
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE execution_session
                SET status = %s, updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (status, now, session_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_session(row)

    def suspend_session(
        self,
        session_id: str,
        waiting_reason: str,
        wake_after: str | None = None,
        wake_condition: dict[str, Any] | None = None,
    ) -> ExecutionSession | None:
        now = _now_iso()
        wake_condition_json = json.dumps(wake_condition) if wake_condition else None
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE execution_session
                SET status = 'suspended',
                    waiting_reason = %s,
                    wake_after = %s,
                    wake_condition_json = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (waiting_reason, wake_after, wake_condition_json, now, session_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    def resume_session(self, session_id: str) -> ExecutionSession | None:
        now = _now_iso()
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE execution_session
                SET status = 'active',
                    waiting_reason = NULL,
                    wake_after = NULL,
                    wake_condition_json = NULL,
                    updated_at = %s
                WHERE id = %s
                  AND status IN ('suspended', 'waiting_internal', 'waiting_external')
                RETURNING *
                """,
                (now, session_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT * FROM execution_session WHERE id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_session(row)
        self._commit()
        return _row_to_session(row)

    def update_session_phase(
        self,
        session_id: str,
        phase: str,
        strategy_name: str | None = None,
    ) -> ExecutionSession | None:
        now = _now_iso()
        if strategy_name is not None:
            sql = """
                UPDATE execution_session
                SET current_phase = %s, strategy_name = %s, updated_at = %s
                WHERE id = %s
                RETURNING *
            """
            params = (phase, strategy_name, now, session_id)
        else:
            sql = """
                UPDATE execution_session
                SET current_phase = %s, updated_at = %s
                WHERE id = %s
                RETURNING *
            """
            params = (phase, now, session_id)
        with self._connection.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_session(row)

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
        ckpt_id = _generate_id()
        now = _now_iso()
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(phase_index), 0) + 1 as next_index FROM execution_checkpoint WHERE session_id = %s AND phase = %s",
                (session_id, phase),
            )
            phase_index_row = cur.fetchone()
            phase_index = int(
                _row_value(
                    phase_index_row,
                    "next_index",
                    phase_index_row[0]
                    if phase_index_row is not None
                    and not isinstance(phase_index_row, dict)
                    and hasattr(phase_index_row, "__getitem__")
                    else 1,
                )
                or 1
            )
            cur.execute(
                """
                INSERT INTO execution_checkpoint
                    (id, session_id, phase, phase_index, summary,
                     artifacts_json, tool_state_json, subtasks_json,
                     failure_context_json, next_action_hint,
                     next_action_params_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ckpt_id,
                    session_id,
                    phase,
                    phase_index,
                    summary,
                    json.dumps(artifacts) if artifacts else None,
                    json.dumps(tool_state) if tool_state else None,
                    json.dumps(subtasks) if subtasks else None,
                    json.dumps(failure_context) if failure_context else None,
                    next_action_hint,
                    json.dumps(next_action_params) if next_action_params else None,
                    now,
                ),
            )
            cur.execute(
                """
                UPDATE execution_session
                SET last_checkpoint_id = %s, updated_at = %s
                WHERE id = %s
                """,
                (ckpt_id, now, session_id),
            )
        self._commit()
        return ExecutionCheckpoint(
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
            created_at=now,
        )

    def get_latest_checkpoint(self, session_id: str) -> ExecutionCheckpoint | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_checkpoint
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_checkpoint(row)

    def record_policy_resolution(
        self,
        *,
        session_id: str,
        work_id: str,
        risk_level: str,
        trigger_reason: str,
        evidence_json: dict[str, Any] | None = None,
        resolution: str,
        resolution_detail_json: dict[str, Any] | None = None,
        applied: bool = False,
    ) -> PolicyResolutionRecord | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO policy_resolution
                    (session_id, work_id, risk_level, trigger_reason,
                     evidence_json, resolution, resolution_detail_json, applied)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    session_id,
                    work_id,
                    risk_level,
                    trigger_reason,
                    json.dumps(evidence_json) if evidence_json is not None else None,
                    resolution,
                    json.dumps(resolution_detail_json)
                    if resolution_detail_json is not None
                    else None,
                    applied,
                ),
            )
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_policy_resolution(row)

    def get_latest_policy_resolution(
        self, session_id: str
    ) -> PolicyResolutionRecord | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM policy_resolution
                WHERE session_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_policy_resolution(row)

    def list_checkpoints(self, session_id: str) -> list[ExecutionCheckpoint]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_checkpoint
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [_row_to_checkpoint(row) for row in rows]

    def build_resume_context(self, session_id: str) -> str:
        session = self.get_session(session_id)
        if session is None:
            return ""
        parts: list[str] = []
        if session.context_summary:
            parts.append(f"Context: {session.context_summary}")
        if session.strategy_name:
            parts.append(f"Strategy: {session.strategy_name}")
        ckpt = self.get_latest_checkpoint(session_id)
        if ckpt:
            parts.append(f"Last phase: {ckpt.phase} (index {ckpt.phase_index})")
            parts.append(f"Last summary: {ckpt.summary}")
            if ckpt.next_action_hint:
                parts.append(f"Next action: {ckpt.next_action_hint}")
            if ckpt.artifacts:
                parts.append(
                    f"Artifacts: {json.dumps(ckpt.artifacts, ensure_ascii=False)}"
                )
        return "\n".join(parts)

    def list_active_sessions_for_work(self, work_id: str) -> list[ExecutionSession]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_session
                WHERE work_id = %s
                  AND status NOT IN ('completed', 'failed_terminal', 'human_required')
                ORDER BY created_at ASC
                """,
                (work_id,),
            )
            rows = cur.fetchall()
        return [_row_to_session(row) for row in rows]

    def list_wakeable_sessions(self) -> list[ExecutionSession]:
        now = _now_iso()
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_session
                WHERE status IN ('suspended', 'waiting_internal', 'waiting_external')
                  AND wake_after IS NOT NULL
                  AND wake_after <= %s
                """,
                (now,),
            )
            rows = cur.fetchall()
        return [_row_to_session(row) for row in rows]

    def list_all_sessions(self) -> list[ExecutionSession]:
        with self._connection.cursor() as cur:
            cur.execute("SELECT * FROM execution_session ORDER BY created_at ASC")
            rows = cur.fetchall()
        return [_row_to_session(row) for row in rows]

    def list_timed_out_sessions(
        self, *, max_age_seconds: int = 86400
    ) -> list[ExecutionSession]:
        now = _now_iso()
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_session
                WHERE status NOT IN ('completed', 'failed_terminal', 'human_required')
                  AND created_at < (NOW() - INTERVAL '%s seconds')
                """,
                (max_age_seconds,),
            )
            rows = cur.fetchall()
        return [_row_to_session(row) for row in rows]

    def abandon_timed_out_sessions(self, *, max_age_seconds: int = 86400) -> list[str]:
        timed_out = self.list_timed_out_sessions(max_age_seconds=max_age_seconds)
        abandoned_ids: list[str] = []
        now = _now_iso()
        for session in timed_out:
            with self._connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_session
                    SET status = 'failed_terminal',
                        waiting_reason = 'timeout',
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (now, session.id),
                )
            self._commit()
            self.append_checkpoint(
                session.id,
                phase=session.current_phase,
                summary=f"session abandoned: exceeded {max_age_seconds}s lifetime",
                failure_context={"max_age_seconds": max_age_seconds},
                next_action_hint="restart",
            )
            abandoned_ids.append(session.id)
        return abandoned_ids
