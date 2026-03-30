from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from stardrifter_orchestration_mvp.models import ExecutionSession
from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager
from stardrifter_orchestration_mvp.session_runtime_loop import (
    ExecutorResult,
    fire_wakeup_for_event,
    process_session_wakeups,
    run_session_iteration,
    run_session_to_completion,
)
from stardrifter_orchestration_mvp.wakeup_dispatcher import InMemoryWakeupDispatcher


def _make_executor(payload: dict[str, Any]):
    def executor_fn(**kwargs: Any) -> ExecutorResult:
        return ExecutorResult(success=True, payload=payload)

    return executor_fn


def _make_failing_executor():
    def executor_fn(**kwargs: Any) -> ExecutorResult:
        raise RuntimeError("executor crash")

    return executor_fn


class TestRunSessionIteration:
    def test_checkpoint_payload(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1", current_phase="researching")
        executor = _make_executor(
            {
                "execution_kind": "checkpoint",
                "phase": "researching",
                "summary": "Found 3 modules",
                "artifacts": {"files": ["a.py"]},
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "checkpoint"
        assert result.checkpoint is not None
        assert result.checkpoint.summary == "Found 3 modules"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.current_phase == "researching"

    def test_wait_payload_suspends_session(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor(
            {
                "execution_kind": "wait",
                "wait_type": "subagent_result",
                "summary": "Waiting for subagent",
                "resume_hint": "Resume at synthesis",
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "suspended"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "suspended"
        assert len(wake.list_pending()) == 1

    def test_terminal_done(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor({"outcome": "done", "summary": "task completed"})
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "completed"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "completed"

    def test_terminal_needs_decision(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor(
            {
                "outcome": "needs_decision",
                "summary": "need approval",
                "decision_required": True,
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "terminalized"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "human_required"

    def test_retry_intent(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor(
            {
                "execution_kind": "retry_intent",
                "failure_reason": "timeout",
                "summary": "executor timed out",
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "retry"
        assert result.checkpoint is not None
        assert result.checkpoint.failure_context == {"failure_reason": "timeout"}

    def test_executor_crash(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=_make_failing_executor(),
        )
        assert result.action == "executor_error"
        assert result.error == "executor crash"

    def test_skips_terminal_session(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.update_session_status(session.id, "completed")
        terminal_session = mgr.get_session(session.id)
        assert terminal_session is not None
        result = run_session_iteration(
            session=terminal_session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=_make_executor({"outcome": "done"}),
        )
        assert result.action == "skip"


class TestProcessSessionWakeups:
    def test_fires_and_resumes(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="timer")
        wake.register_wakeup(
            session_id=session.id,
            work_id="w1",
            wake_type="timer",
            wake_condition={},
            scheduled_at="2000-01-01T00:00:00Z",
        )
        resumed = process_session_wakeups(session_manager=mgr, wakeup_dispatcher=wake)
        assert session.id in resumed
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"

    def test_no_fireable_returns_empty(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        resumed = process_session_wakeups(session_manager=mgr, wakeup_dispatcher=wake)
        assert resumed == []


class TestPolicyEngineIntegration:
    def test_needs_decision_with_policy_retry(self) -> None:
        from stardrifter_orchestration_mvp.policy_engine import evaluate_policy

        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor(
            {
                "outcome": "needs_decision",
                "summary": "unclear scope",
                "decision_required": True,
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
            policy_engine_fn=evaluate_policy,
        )
        assert result.action == "policy_retry"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"

    def test_needs_decision_with_policy_human_required_after_many_attempts(
        self,
    ) -> None:
        from stardrifter_orchestration_mvp.policy_engine import evaluate_policy

        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1", attempt_index=5)
        executor = _make_executor(
            {
                "outcome": "needs_decision",
                "summary": "unclear scope",
                "decision_required": True,
            }
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
            policy_engine_fn=evaluate_policy,
        )
        assert result.action == "terminalized"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "human_required"

    def test_blocked_with_auto_resolve(self) -> None:
        from stardrifter_orchestration_mvp.policy_engine import evaluate_policy

        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        executor = _make_executor(
            {"outcome": "blocked", "summary": "dirty worktree detected"}
        )
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
            policy_engine_fn=evaluate_policy,
        )
        assert result.action == "auto_resolve"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"


class TestFireWakeupForEvent:
    def test_fires_matching_pending_wakeup(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="subagent_result")
        wake.register_wakeup(
            session_id=session.id,
            work_id="w1",
            wake_type="subagent_result",
            wake_condition={},
        )
        fired = fire_wakeup_for_event(
            wakeup_dispatcher=wake,
            session_manager=mgr,
            session_id=session.id,
            wake_type="subagent_result",
        )
        assert fired is True
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"

    def test_no_match_returns_false(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="timer")
        wake.register_wakeup(
            session_id=session.id,
            work_id="w1",
            wake_type="timer",
            wake_condition={},
        )
        fired = fire_wakeup_for_event(
            wakeup_dispatcher=wake,
            session_manager=mgr,
            session_id=session.id,
            wake_type="subagent_result",
        )
        assert fired is False


class TestRunSessionToCompletion:
    def test_single_iteration_done(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            call_count["n"] += 1
            return ExecutorResult(
                success=True, payload={"outcome": "done", "summary": "done"}
            )

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
        )
        assert result.final_status == "completed"
        assert result.iterations == 1
        assert call_count["n"] == 1

    def test_multi_checkpoint_then_done(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            call_count["n"] += 1
            if call_count["n"] < 3:
                return ExecutorResult(
                    success=True,
                    payload={
                        "execution_kind": "checkpoint",
                        "phase": "researching",
                        "summary": f"step {call_count['n']}",
                    },
                )
            return ExecutorResult(
                success=True, payload={"outcome": "done", "summary": "done"}
            )

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
        )
        assert result.final_status == "completed"
        assert result.iterations == 3
        assert call_count["n"] == 3

    def test_wait_then_resume_with_wait_fn(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ExecutorResult(
                    success=True,
                    payload={
                        "execution_kind": "wait",
                        "wait_type": "tool_result",
                        "summary": "waiting for tool",
                    },
                )
            return ExecutorResult(
                success=True, payload={"outcome": "done", "summary": "done"}
            )

        def wait_fn(**kwargs: Any) -> bool:
            return True

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
            wait_fn=wait_fn,
        )
        assert result.final_status == "completed"
        assert result.iterations == 2
        assert call_count["n"] == 2

    def test_max_iterations_stops_loop(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "researching",
                    "summary": "still going",
                },
            )

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
            max_iterations=3,
        )
        assert result.iterations == 3
        assert result.final_status == "active"

    def test_needs_decision_without_policy_terminalizes(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            return ExecutorResult(
                success=True,
                payload={
                    "outcome": "needs_decision",
                    "summary": "unclear",
                    "decision_required": True,
                },
            )

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
        )
        assert result.final_status == "human_required"
        assert result.iterations == 1

    def test_needs_decision_with_policy_retries(self) -> None:
        from stardrifter_orchestration_mvp.policy_engine import evaluate_policy

        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return ExecutorResult(
                    success=True,
                    payload={
                        "outcome": "needs_decision",
                        "summary": "unclear scope",
                        "decision_required": True,
                    },
                )
            return ExecutorResult(
                success=True, payload={"outcome": "done", "summary": "resolved"}
            )

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
            policy_engine_fn=evaluate_policy,
        )
        assert result.final_status == "completed"
        assert result.iterations == 3
