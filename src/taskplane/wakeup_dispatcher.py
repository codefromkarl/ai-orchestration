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
            scheduled_at=scheduled_at or now,
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
