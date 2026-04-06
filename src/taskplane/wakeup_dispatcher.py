from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .models import ExecutionWakeup


def _generate_id() -> str:
    return secrets.token_hex(16)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_scheduled_at(wake_type: str, scheduled_at: str | None) -> str:
    if isinstance(scheduled_at, str) and scheduled_at.strip():
        return scheduled_at.strip()
    if wake_type == "timer":
        return _now_iso()
    return "9999-12-31T23:59:59+00:00"


def _row_to_wakeup(row: Any) -> ExecutionWakeup:
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
        import json

        try:
            wake_condition = json.loads(wake_condition)
        except (json.JSONDecodeError, TypeError):
            wake_condition = {}
    if not isinstance(wake_condition, dict):
        wake_condition = {}
    return ExecutionWakeup(
        id=str(_val("id")),
        session_id=str(_val("session_id")),
        work_id=str(_val("work_id")),
        wake_type=str(_val("wake_type") or ""),
        wake_condition=wake_condition,
        status=str(_val("status") or "pending"),
        scheduled_at=_val("scheduled_at").isoformat() if _val("scheduled_at") else None,
        fired_at=_val("fired_at").isoformat() if _val("fired_at") else None,
        created_at=_val("created_at").isoformat() if _val("created_at") else None,
    )


class PostgresWakeupDispatcher:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _commit(self) -> None:
        commit = getattr(self._connection, "commit", None)
        if callable(commit):
            commit()

    def register_wakeup(
        self,
        *,
        session_id: str,
        work_id: str,
        wake_type: str,
        wake_condition: dict[str, Any],
        scheduled_at: str | None = None,
    ) -> ExecutionWakeup:
        import json

        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_wakeup (
                    session_id,
                    work_id,
                    wake_type,
                    wake_condition_json,
                    status,
                    scheduled_at
                )
                VALUES (%s, %s, %s, %s::jsonb, 'pending', COALESCE(%s::timestamptz, NOW()))
                RETURNING *
                """,
                (
                    session_id,
                    work_id,
                    wake_type,
                    json.dumps(wake_condition, ensure_ascii=False),
                    _resolve_scheduled_at(wake_type, scheduled_at),
                ),
            )
            row = cur.fetchone()
        self._commit()
        if row is None:
            raise RuntimeError("failed to register wakeup")
        return _row_to_wakeup(row)

    def fire_wakeup(self, wakeup_id: str) -> ExecutionWakeup | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE execution_wakeup
                SET status = 'fired',
                    fired_at = NOW()
                WHERE id = %s
                  AND status = 'pending'
                RETURNING *
                """,
                (wakeup_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_wakeup(row)

    def cancel_wakeup(self, wakeup_id: str) -> ExecutionWakeup | None:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE execution_wakeup
                SET status = 'cancelled'
                WHERE id = %s
                  AND status = 'pending'
                RETURNING *
                """,
                (wakeup_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        self._commit()
        return _row_to_wakeup(row)

    def scan_fireable(self) -> list[ExecutionWakeup]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM execution_wakeup
                WHERE status = 'pending'
                  AND scheduled_at <= NOW()
                ORDER BY scheduled_at ASC, created_at ASC
                """,
                (),
            )
            rows = cur.fetchall()
        return [_row_to_wakeup(row) for row in rows]

    def process_fireable(self) -> list[str]:
        fired_ids: list[str] = []
        for wakeup in self.scan_fireable():
            fired = self.fire_wakeup(wakeup.id)
            if fired is not None:
                fired_ids.append(fired.session_id)
        return fired_ids

    def list_by_session(self, session_id: str) -> list[ExecutionWakeup]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM execution_wakeup
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [_row_to_wakeup(row) for row in rows]

    def list_pending(self) -> list[ExecutionWakeup]:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM execution_wakeup
                WHERE status = 'pending'
                ORDER BY scheduled_at ASC, created_at ASC
                """,
                (),
            )
            rows = cur.fetchall()
        return [_row_to_wakeup(row) for row in rows]


@dataclass
class InMemoryWakeupDispatcher:
    wakeups_by_id: dict[str, ExecutionWakeup] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def register_wakeup(
        self,
        *,
        session_id: str,
        work_id: str,
        wake_type: str,
        wake_condition: dict[str, Any],
        scheduled_at: str | None = None,
    ) -> ExecutionWakeup:
        wakeup_id = _generate_id()
        now = _now_iso()
        wakeup = ExecutionWakeup(
            id=wakeup_id,
            session_id=session_id,
            work_id=work_id,
            wake_type=wake_type,
            wake_condition=wake_condition,
            status="pending",
            scheduled_at=_resolve_scheduled_at(wake_type, scheduled_at),
            created_at=now,
        )
        with self._lock:
            self.wakeups_by_id[wakeup_id] = wakeup
        return wakeup

    def fire_wakeup(self, wakeup_id: str) -> ExecutionWakeup | None:
        with self._lock:
            wakeup = self.wakeups_by_id.get(wakeup_id)
            if wakeup is None or wakeup.status != "pending":
                return None
            updated = ExecutionWakeup(
                id=wakeup.id,
                session_id=wakeup.session_id,
                work_id=wakeup.work_id,
                wake_type=wakeup.wake_type,
                wake_condition=wakeup.wake_condition,
                status="fired",
                scheduled_at=wakeup.scheduled_at,
                fired_at=_now_iso(),
                created_at=wakeup.created_at,
            )
            self.wakeups_by_id[wakeup_id] = updated
            return updated

    def cancel_wakeup(self, wakeup_id: str) -> ExecutionWakeup | None:
        with self._lock:
            wakeup = self.wakeups_by_id.get(wakeup_id)
            if wakeup is None or wakeup.status != "pending":
                return None
            updated = ExecutionWakeup(
                id=wakeup.id,
                session_id=wakeup.session_id,
                work_id=wakeup.work_id,
                wake_type=wakeup.wake_type,
                wake_condition=wakeup.wake_condition,
                status="cancelled",
                scheduled_at=wakeup.scheduled_at,
                fired_at=wakeup.fired_at,
                created_at=wakeup.created_at,
            )
            self.wakeups_by_id[wakeup_id] = updated
            return updated

    def scan_fireable(self) -> list[ExecutionWakeup]:
        now = _now_iso()
        result: list[ExecutionWakeup] = []
        for wakeup in self.wakeups_by_id.values():
            if wakeup.status != "pending":
                continue
            if wakeup.scheduled_at is not None and wakeup.scheduled_at <= now:
                result.append(wakeup)
        return result

    def process_fireable(self) -> list[str]:
        fired_ids: list[str] = []
        for wakeup in self.scan_fireable():
            fired = self.fire_wakeup(wakeup.id)
            if fired is not None:
                fired_ids.append(fired.session_id)
        return fired_ids

    def list_by_session(self, session_id: str) -> list[ExecutionWakeup]:
        return [w for w in self.wakeups_by_id.values() if w.session_id == session_id]

    def list_pending(self) -> list[ExecutionWakeup]:
        return [w for w in self.wakeups_by_id.values() if w.status == "pending"]
