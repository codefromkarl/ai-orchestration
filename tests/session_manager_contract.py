from __future__ import annotations

from typing import Any

from taskplane.models import (
    ExecutionCheckpoint,
    ExecutionSession,
    SessionStatus,
)


def run_session_manager_contract_tests(mgr: Any) -> None:
    _test_create_and_get(mgr)
    _test_update_status(mgr)
    _test_suspend_and_resume(mgr)
    _test_checkpoint_ordering(mgr)
    _test_checkpoint_increments_phase_index(mgr)
    _test_resume_context_from_checkpoints(mgr)
    _test_policy_resolution_recording(mgr)
    _test_list_active_sessions(mgr)
    _test_wakeable_sessions(mgr)
    _test_nonexistent_session_returns_none(mgr)


def _test_create_and_get(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w1", current_phase="researching")
    assert session.work_id == "contract-w1"
    assert session.status == "active"
    assert session.current_phase == "researching"
    got = mgr.get_session(session.id)
    assert got is not None
    assert got.id == session.id
    assert got.work_id == "contract-w1"


def _test_update_status(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w2")
    updated = mgr.update_session_status(session.id, "completed")
    assert updated is not None
    assert updated.status == "completed"
    got = mgr.get_session(session.id)
    assert got is not None
    assert got.status == "completed"


def _test_suspend_and_resume(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w3")
    suspended = mgr.suspend_session(
        session.id,
        waiting_reason="timer",
        wake_after="2099-01-01T00:00:00Z",
    )
    assert suspended is not None
    assert suspended.status == "suspended"
    assert suspended.waiting_reason == "timer"
    resumed = mgr.resume_session(session.id)
    assert resumed is not None
    assert resumed.status == "active"
    assert resumed.waiting_reason is None


def _test_checkpoint_ordering(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w4")
    c1 = mgr.append_checkpoint(session.id, phase="researching", summary="step 1")
    c2 = mgr.append_checkpoint(session.id, phase="researching", summary="step 2")
    c3 = mgr.append_checkpoint(session.id, phase="implementing", summary="step 3")
    assert c1 is not None and c2 is not None and c3 is not None
    assert c1.phase_index == 1
    assert c2.phase_index == 2
    assert c3.phase_index == 1
    checkpoints = mgr.list_checkpoints(session.id)
    assert len(checkpoints) == 3
    assert [c.summary for c in checkpoints] == ["step 1", "step 2", "step 3"]
    latest = mgr.get_latest_checkpoint(session.id)
    assert latest is not None
    assert latest.id == c3.id


def _test_checkpoint_increments_phase_index(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w5")
    mgr.append_checkpoint(session.id, phase="researching", summary="r1")
    mgr.append_checkpoint(session.id, phase="researching", summary="r2")
    mgr.append_checkpoint(session.id, phase="researching", summary="r3")
    ckpts = mgr.list_checkpoints(session.id)
    assert [c.phase_index for c in ckpts] == [1, 2, 3]


def _test_resume_context_from_checkpoints(mgr: Any) -> None:
    session = mgr.create_session(
        work_id="contract-w6",
        current_phase="researching",
        strategy_name="narrow_scope",
        context_summary="Examining auth module",
    )
    mgr.append_checkpoint(
        session.id,
        phase="researching",
        summary="Found 3 modules",
        next_action_hint="implement fix",
    )
    ctx = mgr.build_resume_context(session.id)
    assert "Examining auth module" in ctx
    assert "narrow_scope" in ctx
    assert "Found 3 modules" in ctx
    assert "implement fix" in ctx


def _test_policy_resolution_recording(mgr: Any) -> None:
    session = mgr.create_session(work_id="contract-w-policy")
    record = mgr.record_policy_resolution(
        session_id=session.id,
        work_id=session.work_id,
        risk_level="medium",
        trigger_reason="needs_decision with low attempt count",
        evidence_json={"outcome": "needs_decision"},
        resolution="retry_strategy",
        resolution_detail_json={"strategy": "retry_with_narrowed_scope"},
        applied=True,
    )
    assert record is not None
    assert record.session_id == session.id
    assert record.work_id == session.work_id
    assert record.risk_level == "medium"
    assert record.trigger_reason == "needs_decision with low attempt count"
    assert record.resolution == "retry_strategy"
    assert record.applied is True
    latest = mgr.get_latest_policy_resolution(session.id)
    assert latest is not None
    assert latest == record


def _test_list_active_sessions(mgr: Any) -> None:
    s1 = mgr.create_session(work_id="contract-w7")
    s2 = mgr.create_session(work_id="contract-w7")
    mgr.create_session(work_id="contract-w8")
    mgr.update_session_status(s2.id, "completed")
    active = mgr.list_active_sessions_for_work("contract-w7")
    active_ids = {s.id for s in active}
    assert s1.id in active_ids
    assert s2.id not in active_ids


def _test_wakeable_sessions(mgr: Any) -> None:
    s1 = mgr.create_session(work_id="contract-w9")
    mgr.suspend_session(
        s1.id, waiting_reason="timer", wake_after="2000-01-01T00:00:00Z"
    )
    wakeable = mgr.list_wakeable_sessions()
    assert any(s.id == s1.id for s in wakeable)


def _test_nonexistent_session_returns_none(mgr: Any) -> None:
    assert mgr.get_session("nonexistent") is None
    assert mgr.resume_session("nonexistent") is None
    assert mgr.get_latest_checkpoint("nonexistent") is None
    assert mgr.get_latest_policy_resolution("nonexistent") is None
    assert mgr.append_checkpoint("nonexistent", phase="x", summary="y") is None
