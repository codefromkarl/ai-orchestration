from __future__ import annotations

from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager


class TestInMemorySessionManager:
    def test_create_session(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1", current_phase="researching")
        assert session.work_id == "work-1"
        assert session.status == "active"
        assert session.current_phase == "researching"
        assert mgr.get_session(session.id) is session

    def test_suspend_and_resume(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1")
        suspended = mgr.suspend_session(
            session.id,
            waiting_reason="waiting for subagent",
            wake_after="2099-01-01T00:00:00Z",
        )
        assert suspended is not None
        assert suspended.status == "suspended"
        assert suspended.waiting_reason == "waiting for subagent"
        resumed = mgr.resume_session(session.id)
        assert resumed is not None
        assert resumed.status == "active"
        assert resumed.waiting_reason is None

    def test_resume_non_suspended_is_noop(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1")
        result = mgr.resume_session(session.id)
        assert result is not None
        assert result.status == "active"

    def test_resume_nonexistent_returns_none(self) -> None:
        mgr = InMemorySessionManager()
        assert mgr.resume_session("nonexistent") is None

    def test_append_checkpoint(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1", current_phase="researching")
        ckpt = mgr.append_checkpoint(
            session.id,
            phase="researching",
            summary="Found 3 candidate modules",
            artifacts={"files": ["a.py", "b.py"]},
        )
        assert ckpt is not None
        assert ckpt.phase == "researching"
        assert ckpt.phase_index == 1
        assert ckpt.summary == "Found 3 candidate modules"
        assert ckpt.artifacts == {"files": ["a.py", "b.py"]}
        latest = mgr.get_latest_checkpoint(session.id)
        assert latest is ckpt

    def test_checkpoint_phase_index_increments(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1")
        mgr.append_checkpoint(session.id, phase="researching", summary="first")
        mgr.append_checkpoint(session.id, phase="researching", summary="second")
        ckpt3 = mgr.append_checkpoint(session.id, phase="implementing", summary="third")
        assert ckpt3 is not None
        assert ckpt3.phase_index == 1
        ckpts = mgr.list_checkpoints(session.id)
        assert len(ckpt3.id) > 0
        assert ckpts[0].phase_index == 1
        assert ckpts[1].phase_index == 2
        assert ckpts[2].phase_index == 1

    def test_list_active_sessions_for_work(self) -> None:
        mgr = InMemorySessionManager()
        s1 = mgr.create_session(work_id="work-1")
        s2 = mgr.create_session(work_id="work-1")
        s3 = mgr.create_session(work_id="work-2")
        mgr.update_session_status(s2.id, "completed")
        active = mgr.list_active_sessions_for_work("work-1")
        assert len(active) == 1
        assert active[0].id == s1.id

    def test_list_wakeable_sessions(self) -> None:
        mgr = InMemorySessionManager()
        s1 = mgr.create_session(work_id="work-1")
        mgr.suspend_session(
            s1.id, waiting_reason="timer", wake_after="2000-01-01T00:00:00Z"
        )
        wakeable = mgr.list_wakeable_sessions()
        assert len(wakeable) == 1
        assert wakeable[0].id == s1.id

    def test_list_wakeable_excludes_active(self) -> None:
        mgr = InMemorySessionManager()
        s1 = mgr.create_session(work_id="work-1")
        s2 = mgr.create_session(work_id="work-1")
        mgr.suspend_session(
            s2.id, waiting_reason="timer", wake_after="2099-01-01T00:00:00Z"
        )
        wakeable = mgr.list_wakeable_sessions()
        assert len(wakeable) == 0

    def test_build_resume_context(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(
            work_id="work-1",
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
        assert "implement fix" in ctx
        assert "Found 3 modules" in ctx

    def test_build_resume_context_empty_for_nonexistent(self) -> None:
        mgr = InMemorySessionManager()
        assert mgr.build_resume_context("nonexistent") == ""

    def test_update_session_phase(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1", current_phase="planning")
        updated = mgr.update_session_phase(
            session.id, "implementing", strategy_name="direct"
        )
        assert updated is not None
        assert updated.current_phase == "implementing"
        assert updated.strategy_name == "direct"

    def test_append_checkpoint_for_nonexistent_session(self) -> None:
        mgr = InMemorySessionManager()
        ckpt = mgr.append_checkpoint("nonexistent", phase="x", summary="y")
        assert ckpt is None

    def test_abandon_timed_out_sessions(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1")
        assert len(mgr.list_timed_out_sessions(max_age_seconds=0)) == 1
        abandoned = mgr.abandon_timed_out_sessions(max_age_seconds=0)
        assert session.id in abandoned
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "failed_terminal"
        ckpt = mgr.get_latest_checkpoint(session.id)
        assert ckpt is not None
        assert "abandoned" in ckpt.summary

    def test_list_timed_out_excludes_terminal(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="work-1")
        mgr.update_session_status(session.id, "completed")
        assert len(mgr.list_timed_out_sessions(max_age_seconds=0)) == 0
