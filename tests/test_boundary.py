from __future__ import annotations

from typing import Any

from stardrifter_orchestration_mvp.executor_adapter import parse_executor_output
from stardrifter_orchestration_mvp.execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_WAIT_MARKER,
    classify_execution_payload,
    validate_checkpoint_payload,
    validate_wait_payload,
)
from stardrifter_orchestration_mvp.policy_engine import evaluate_policy
from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager
from stardrifter_orchestration_mvp.session_runtime_loop import (
    ExecutorResult,
    run_session_iteration,
    run_session_to_completion,
)
from stardrifter_orchestration_mvp.wakeup_dispatcher import InMemoryWakeupDispatcher


class TestSessionManagerBoundaries:
    def test_create_and_immediately_complete(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "completed")
        assert mgr.get_session(session.id).status == "completed"
        assert len(mgr.list_active_sessions_for_work("w1")) == 0

    def test_suspend_twice_overwrites(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="first")
        mgr.suspend_session(session.id, waiting_reason="second")
        got = mgr.get_session(session.id)
        assert got.waiting_reason == "second"

    def test_resume_active_session_is_noop(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        result = mgr.resume_session(session.id)
        assert result is not None
        assert result.status == "active"

    def test_resume_completed_is_noop(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "completed")
        result = mgr.resume_session(session.id)
        assert result is not None
        assert result.status == "completed"

    def test_checkpoint_on_nonexistent_session(self) -> None:
        mgr = InMemorySessionManager()
        ckpt = mgr.append_checkpoint("fake-id", phase="x", summary="y")
        assert ckpt is None

    def test_many_checkpoints_same_phase(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        for i in range(100):
            mgr.append_checkpoint(session.id, phase="researching", summary=f"step {i}")
        ckpts = mgr.list_checkpoints(session.id)
        assert len(ckpts) == 100
        assert ckpts[-1].phase_index == 100

    def test_empty_summary_checkpoint(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        ckpt = mgr.append_checkpoint(session.id, phase="researching", summary="")
        assert ckpt is not None
        assert ckpt.summary == ""

    def test_checkpoint_with_none_artifacts(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        ckpt = mgr.append_checkpoint(
            session.id, phase="researching", summary="test", artifacts=None
        )
        assert ckpt is not None
        assert ckpt.artifacts is None

    def test_resume_context_empty_session(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        ctx = mgr.build_resume_context(session.id)
        assert ctx == ""

    def test_list_active_excludes_all_terminal(self) -> None:
        mgr = InMemorySessionManager()
        s1 = mgr.create_session(work_id="w1")
        s2 = mgr.create_session(work_id="w1")
        mgr.update_session_status(s1.id, "completed")
        mgr.update_session_status(s2.id, "failed_terminal")
        assert len(mgr.list_active_sessions_for_work("w1")) == 0

    def test_wakeable_returns_empty_when_no_suspended(self) -> None:
        mgr = InMemorySessionManager()
        mgr.create_session(work_id="w1")
        assert len(mgr.list_wakeable_sessions()) == 0


class TestWakeupDispatcherBoundaries:
    def test_fire_already_fired_is_noop(self) -> None:
        wake = InMemoryWakeupDispatcher()
        w = wake.register_wakeup(
            session_id="s1", work_id="w1", wake_type="timer", wake_condition={}
        )
        wake.fire_wakeup(w.id)
        result = wake.fire_wakeup(w.id)
        assert result is None

    def test_fire_nonexistent_is_noop(self) -> None:
        wake = InMemoryWakeupDispatcher()
        assert wake.fire_wakeup("nonexistent") is None

    def test_cancel_already_fired_is_noop(self) -> None:
        wake = InMemoryWakeupDispatcher()
        w = wake.register_wakeup(
            session_id="s1", work_id="w1", wake_type="timer", wake_condition={}
        )
        wake.fire_wakeup(w.id)
        assert wake.cancel_wakeup(w.id) is None

    def test_cancel_nonexistent_is_noop(self) -> None:
        wake = InMemoryWakeupDispatcher()
        assert wake.cancel_wakeup("nonexistent") is None

    def test_process_fireable_with_no_pending(self) -> None:
        wake = InMemoryWakeupDispatcher()
        assert wake.process_fireable() == []

    def test_scan_fireable_excludes_fired(self) -> None:
        wake = InMemoryWakeupDispatcher()
        w = wake.register_wakeup(
            session_id="s1",
            work_id="w1",
            wake_type="timer",
            wake_condition={},
            scheduled_at="2000-01-01T00:00:00Z",
        )
        wake.fire_wakeup(w.id)
        assert wake.scan_fireable() == []

    def test_scan_fireable_excludes_cancelled(self) -> None:
        wake = InMemoryWakeupDispatcher()
        w = wake.register_wakeup(
            session_id="s1",
            work_id="w1",
            wake_type="timer",
            wake_condition={},
            scheduled_at="2000-01-01T00:00:00Z",
        )
        wake.cancel_wakeup(w.id)
        assert wake.scan_fireable() == []

    def test_list_by_session_empty(self) -> None:
        wake = InMemoryWakeupDispatcher()
        assert wake.list_by_session("s1") == []

    def test_multiple_wakeups_same_session(self) -> None:
        wake = InMemoryWakeupDispatcher()
        wake.register_wakeup(
            session_id="s1", work_id="w1", wake_type="timer", wake_condition={}
        )
        wake.register_wakeup(
            session_id="s1",
            work_id="w1",
            wake_type="subagent_result",
            wake_condition={},
        )
        assert len(wake.list_by_session("s1")) == 2


class TestRuntimeLoopBoundaries:
    def _make_executor(self, payload: dict[str, Any]):
        def fn(**kw: Any) -> ExecutorResult:
            return ExecutorResult(success=True, payload=payload)

        return fn

    def test_iteration_on_completed_session(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "completed")
        result = run_session_iteration(
            session=mgr.get_session(session.id),
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "done"}),
        )
        assert result.action == "skip"

    def test_iteration_on_human_required_session(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "human_required")
        result = run_session_iteration(
            session=mgr.get_session(session.id),
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "done"}),
        )
        assert result.action == "skip"

    def test_max_iterations_zero(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "done"}),
            max_iterations=0,
        )
        assert result.iterations == 0
        assert result.final_status == "active"

    def test_max_iterations_one_with_immediate_done(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "done"}),
            max_iterations=1,
        )
        assert result.iterations == 1
        assert result.final_status == "completed"

    def test_nonexistent_session_id(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        result = run_session_to_completion(
            session_id="nonexistent",
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "done"}),
        )
        assert result.final_status == "not_found"

    def test_unknown_payload_action(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"something": "unexpected"}),
        )
        assert result.action == "unexpected"

    def test_executor_returns_empty_payload(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({}),
        )
        assert result.action == "unexpected"

    def test_already_satisfied_outcome(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "already_satisfied"}),
        )
        assert result.action == "completed"

    def test_blocked_outcome_terminalizes(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=self._make_executor({"outcome": "blocked", "summary": "stuck"}),
        )
        assert result.action == "terminalized"
        assert mgr.get_session(session.id).status == "failed_terminal"


class TestPolicyEngineBoundaries:
    def test_attempt_index_exact_threshold(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"outcome": "needs_decision", "summary": "unclear"},
            attempt_index=3,
        )
        assert res.resolution == "human_required"

    def test_attempt_index_one_below_threshold(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"outcome": "needs_decision", "summary": "unclear"},
            attempt_index=2,
        )
        assert res.resolution == "retry_strategy"

    def test_timeout_exact_threshold(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "timeout"},
            attempt_index=5,
        )
        assert res.resolution == "human_required"

    def test_timeout_one_below_threshold(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "timeout"},
            attempt_index=4,
        )
        assert res.resolution == "retry_strategy"

    def test_empty_failure_context(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context=None,
            attempt_index=1,
        )
        assert res.resolution == "retry_strategy"

    def test_security_keyword_forces_human(self) -> None:
        from stardrifter_orchestration_mvp.models import ExecutionSession

        session = ExecutionSession(id="s1", work_id="w1", current_phase="planning")
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"summary": "requires security review"},
            attempt_index=1,
        )
        assert res.resolution == "human_required"
        assert res.risk_level == "high"


class TestExecutorAdapterBoundaries:
    def test_both_stdout_and_stderr_have_markers(self) -> None:
        stdout = (
            f'{EXECUTION_RESULT_MARKER}{{"outcome":"blocked","summary":"from stdout"}}'
        )
        stderr = f'{EXECUTION_CHECKPOINT_MARKER}{{"execution_kind":"checkpoint","phase":"researching","summary":"from stderr"}}'
        result = parse_executor_output(stdout, stderr, 0)
        assert result.success is True
        assert result.payload["summary"] == "from stderr"

    def test_marker_after_invalid_json(self) -> None:
        raw = f'not-json\n{{broken}}\n{EXECUTION_RESULT_MARKER}{{"outcome":"done","summary":"ok"}}'
        result = parse_executor_output(raw, "", 0)
        assert result.success is True
        assert result.payload["outcome"] == "done"

    def test_partial_marker_prefix_no_match(self) -> None:
        raw = "STARDRIFTER_EXECUTION_RESULT_JSON incomplete"
        result = parse_executor_output(raw, "", 0)
        assert result.success is False

    def test_marker_with_unicode_payload(self) -> None:
        import json

        payload = {"outcome": "done", "summary": "完成任务 ✓"}
        raw = f"{EXECUTION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}"
        result = parse_executor_output(raw, "", 0)
        assert result.success is True
        assert "完成" in result.payload["summary"]


class TestSessionTimeoutBoundaries:
    def test_zero_max_age_abandons_immediately(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        abandoned = mgr.abandon_timed_out_sessions(max_age_seconds=0)
        assert session.id in abandoned
        assert mgr.get_session(session.id).status == "failed_terminal"

    def test_very_large_max_age_no_abandon(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        abandoned = mgr.abandon_timed_out_sessions(max_age_seconds=999999999)
        assert session.id not in abandoned
        assert mgr.get_session(session.id).status == "active"

    def test_completed_not_abandoned(self) -> None:
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "completed")
        abandoned = mgr.abandon_timed_out_sessions(max_age_seconds=0)
        assert session.id not in abandoned
