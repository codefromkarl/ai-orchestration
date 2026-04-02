from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from taskplane.event_log import InMemoryEventLogRecorder
from taskplane.models import ExecutionCheckpoint, ExecutionSession
from taskplane.policy_engine import PolicyResolution
from taskplane.session_protocol import EXECUTION_KIND_TERMINAL, parse_executor_payload
from taskplane.session_manager import InMemorySessionManager
from taskplane.session_runtime_loop import (
    ExecutorResult,
    SessionTurnRequest,
    fire_wakeup_for_event,
    process_session_wakeups,
    run_session_iteration,
    run_session_to_completion,
)
from taskplane.wakeup_dispatcher import InMemoryWakeupDispatcher


def _make_executor(payload: dict[str, Any]):
    def executor_fn(**kwargs: Any) -> ExecutorResult:
        return ExecutorResult(success=True, payload=payload)

    return executor_fn


def _make_failing_executor():
    def executor_fn(**kwargs: Any) -> ExecutorResult:
        raise RuntimeError("executor crash")

    return executor_fn


class TestRunSessionIteration:
    def test_terminal_outcome_without_execution_kind_is_structured(self) -> None:
        parsed = parse_executor_payload(
            {"outcome": "done", "summary": "task completed"}
        )
        assert parsed.kind == EXECUTION_KIND_TERMINAL
        assert parsed.terminal is not None
        assert parsed.terminal.outcome == "done"

    def test_object_executor_receives_session_turn_request(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1", current_phase="researching")

        class ObjectExecutor:
            def __init__(self) -> None:
                self.requests: list[SessionTurnRequest] = []

            def run_turn(self, request: SessionTurnRequest) -> ExecutorResult:
                self.requests.append(request)
                return ExecutorResult(
                    success=True,
                    payload={"outcome": "done", "summary": "task completed"},
                )

        executor = ObjectExecutor()
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
        )
        assert result.action == "completed"
        assert len(executor.requests) == 1
        request = executor.requests[0]
        assert request.session_id == session.id
        assert request.work_id == "w1"
        assert request.current_phase == "researching"

    def test_resume_context_builder_overrides_session_manager_context(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(
            work_id="w1",
            current_phase="researching",
            context_summary="legacy session summary",
        )

        class ObjectExecutor:
            def __init__(self) -> None:
                self.requests: list[SessionTurnRequest] = []

            def run_turn(self, request: SessionTurnRequest) -> ExecutorResult:
                self.requests.append(request)
                return ExecutorResult(
                    success=True,
                    payload={"outcome": "done", "summary": "task completed"},
                )

        executor = ObjectExecutor()
        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
            resume_context_builder=lambda current: (
                f"Summary:\nresume {current.work_id}\n\nRecent turns:\n- Assistant: keep going"
            ),
        )

        assert result.action == "completed"
        assert executor.requests[0].resume_context.startswith("Summary:\nresume w1")
        assert "legacy session summary" not in executor.requests[0].resume_context

    def test_invalid_executor_payload_is_normalized_to_blocked(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            return ExecutorResult(success=True, payload="not-a-dict")  # type: ignore[arg-type]

        result = run_session_iteration(
            session=session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
        )
        assert result.action == "terminalized"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "failed_terminal"
        assert result.checkpoint is not None
        assert result.checkpoint.failure_context == {
            "outcome": "blocked",
            "reason_code": "invalid-executor-payload",
            "summary": "executor returned a non-dict payload",
        }

    def test_checkpoint_payload(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        recorder = InMemoryEventLogRecorder()
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
            event_recorder=recorder,
        )
        assert result.action == "checkpoint"
        assert result.checkpoint is not None
        assert result.checkpoint.summary == "Found 3 modules"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.current_phase == "researching"
        assert len(recorder.events) == 1
        assert recorder.events[0].category == "session"
        assert recorder.events[0].action == "checkpoint"
        assert recorder.events[0].phase == "researching"
        assert recorder.events[0].summary == "Found 3 modules"

    def test_checkpoint_payload_skips_event_recording_when_checkpoint_is_none(
        self,
    ) -> None:
        class NullCheckpointSessionManager(InMemorySessionManager):
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
                return None

        mgr = NullCheckpointSessionManager()
        wake = InMemoryWakeupDispatcher()
        recorder = InMemoryEventLogRecorder()
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
            event_recorder=recorder,
        )

        assert result.action == "checkpoint"
        assert result.checkpoint is None
        assert recorder.events == []

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
        recorder = InMemoryEventLogRecorder()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="timer")
        wake.register_wakeup(
            session_id=session.id,
            work_id="w1",
            wake_type="timer",
            wake_condition={},
            scheduled_at="2000-01-01T00:00:00Z",
        )
        resumed = process_session_wakeups(
            session_manager=mgr,
            wakeup_dispatcher=wake,
            event_recorder=recorder,
        )
        assert session.id in resumed
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"
        assert len(recorder.events) == 1
        assert recorder.events[0].category == "wakeup"
        assert recorder.events[0].action == "resumed"
        assert recorder.events[0].detail["source"] == "process_session_wakeups"

    def test_no_fireable_returns_empty(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        resumed = process_session_wakeups(session_manager=mgr, wakeup_dispatcher=wake)
        assert resumed == []


class TestPolicyEngineIntegration:
    def test_policy_resolution_is_recorded_after_status_and_checkpoint(self) -> None:
        class RecordingSessionManager:
            def __init__(self) -> None:
                self.calls: list[tuple[str, Any]] = []
                self.session = ExecutionSession(
                    id="session-1",
                    work_id="w1",
                    status="active",
                    current_phase="planning",
                )
                self.latest_checkpoint: ExecutionCheckpoint | None = None

            def get_session(self, session_id: str) -> ExecutionSession | None:
                return self.session

            def get_latest_checkpoint(
                self, session_id: str
            ) -> ExecutionCheckpoint | None:
                return self.latest_checkpoint

            def update_session_status(
                self, session_id: str, status: str
            ) -> ExecutionSession | None:
                self.calls.append(("update_session_status", status))
                self.session = replace(self.session, status=status)
                return self.session

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
                self.calls.append(("append_checkpoint", phase, summary))
                checkpoint = ExecutionCheckpoint(
                    id="checkpoint-1",
                    session_id=session_id,
                    phase=phase,
                    summary=summary,
                    created_at="2026-04-02T00:00:00+00:00",
                )
                self.latest_checkpoint = checkpoint
                return checkpoint

            def record_policy_resolution(self, **kwargs: Any) -> None:
                self.calls.append(
                    (
                        "record_policy_resolution",
                        kwargs["applied"],
                        kwargs["resolution"],
                    )
                )

        mgr = RecordingSessionManager()
        wake = InMemoryWakeupDispatcher()
        executor = _make_executor(
            {
                "outcome": "needs_decision",
                "summary": "unclear scope",
                "decision_required": True,
            }
        )

        def policy_engine_fn(**kwargs: Any) -> PolicyResolution:
            return PolicyResolution(
                resolution="human_required",
                risk_level="high",
                reason="needs_decision after multiple attempts",
                detail={"attempt_index": 5},
            )

        result = run_session_iteration(
            session=mgr.session,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor,
            resume_context="resume context",
            policy_engine_fn=policy_engine_fn,
        )

        assert result.action == "terminalized"
        assert mgr.session.status == "human_required"
        assert mgr.calls == [
            ("update_session_status", "human_required"),
            ("append_checkpoint", "planning", "unclear scope"),
            ("record_policy_resolution", True, "human_required"),
        ]

    def test_needs_decision_with_policy_retry(self) -> None:
        from taskplane.policy_engine import evaluate_policy

        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        recorder = InMemoryEventLogRecorder()
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
            event_recorder=recorder,
        )
        assert result.action == "policy_retry"
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"
        record = mgr.get_latest_policy_resolution(session.id)
        assert record is not None
        assert record.resolution == "retry_strategy"
        assert record.applied is True
        assert record.work_id == "w1"
        assert record.evidence_json is not None
        assert record.evidence_json["outcome"] == "needs_decision"
        assert len(recorder.events) == 2
        assert recorder.events[0].category == "session"
        assert recorder.events[0].action == "checkpoint"
        policy_event = recorder.events[1]
        assert policy_event.category == "policy"
        assert policy_event.action == "policy_retry"
        assert policy_event.resolution == "retry_strategy"

    def test_needs_decision_with_policy_human_required_after_many_attempts(
        self,
    ) -> None:
        from taskplane.policy_engine import evaluate_policy

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
        record = mgr.get_latest_policy_resolution(session.id)
        assert record is not None
        assert record.resolution == "human_required"
        assert record.applied is True
        assert record.risk_level == "high"

    def test_blocked_with_auto_resolve(self) -> None:
        from taskplane.policy_engine import evaluate_policy

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
        record = mgr.get_latest_policy_resolution(session.id)
        assert record is not None
        assert record.resolution == "auto_resolve"
        assert record.applied is True
        assert record.trigger_reason.startswith("Known auto-resolvable")


class TestFireWakeupForEvent:
    def test_fires_matching_pending_wakeup(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        recorder = InMemoryEventLogRecorder()
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
            event_recorder=recorder,
        )
        assert fired is True
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"
        assert len(recorder.events) == 1
        assert recorder.events[0].category == "wakeup"
        assert recorder.events[0].action == "resumed"
        assert recorder.events[0].wakeup_type == "subagent_result"

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

    def test_resume_context_builder_recomputes_context_between_iterations(self) -> None:
        mgr = InMemorySessionManager()
        wake = InMemoryWakeupDispatcher()
        session = mgr.create_session(work_id="w1")
        seen_contexts: list[str] = []

        class ObjectExecutor:
            def run_turn(self, request: SessionTurnRequest) -> ExecutorResult:
                seen_contexts.append(request.resume_context)
                if len(seen_contexts) == 1:
                    return ExecutorResult(
                        success=True,
                        payload={
                            "execution_kind": "checkpoint",
                            "phase": "implementing",
                            "summary": "first checkpoint",
                        },
                    )
                return ExecutorResult(
                    success=True,
                    payload={"outcome": "done", "summary": "done"},
                )

        def builder(current: ExecutionSession) -> str:
            latest = mgr.get_latest_checkpoint(current.id)
            phase = latest.summary if latest is not None else "fresh start"
            return f"Summary:\n{phase}"

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=ObjectExecutor(),
            resume_context_builder=builder,
        )

        assert result.final_status == "completed"
        assert seen_contexts == [
            "Summary:\nfresh start",
            "Summary:\nfirst checkpoint",
        ]

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
        from taskplane.policy_engine import evaluate_policy

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
