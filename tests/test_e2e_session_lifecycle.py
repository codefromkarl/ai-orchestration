from __future__ import annotations

import json
import pytest
from typing import Any

from stardrifter_orchestration_mvp.execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_WAIT_MARKER,
    classify_execution_payload,
    validate_checkpoint_payload,
    validate_wait_payload,
)
from stardrifter_orchestration_mvp.executor_adapter import parse_executor_output
from stardrifter_orchestration_mvp.policy_engine import evaluate_policy
from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager
from stardrifter_orchestration_mvp.session_runtime_loop import (
    ExecutorResult,
    fire_wakeup_for_event,
    run_session_to_completion,
)
from stardrifter_orchestration_mvp.wakeup_dispatcher import InMemoryWakeupDispatcher

from session_fixtures import (
    PATTERN_ALL_CHECKPOINTS,
    PATTERN_BLOCKED_TERMINAL,
    PATTERN_CHECKPOINT_THEN_DONE,
    PATTERN_CHECKPOINT_WAIT_CHECKPOINT_DONE,
    PATTERN_MULTI_CHECKPOINT_THEN_DONE,
    PATTERN_NEEDS_DECISION_THEN_DONE,
    PATTERN_RETRY_THEN_DONE,
    PATTERN_WAIT_THEN_DONE,
    create_active_session,
    make_checkpoint,
    make_done,
    make_executor_sequence,
    make_wait,
    run_pattern,
    setup_session_pair,
)


class TestEndToEndLifecycle:
    def test_checkpoint_then_done(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_CHECKPOINT_THEN_DONE)
        assert result.final_status == "completed"
        assert result.iterations == 2
        session = mgr.get_session(result.session_id)
        assert session is not None
        assert session.status == "completed"
        checkpoints = mgr.list_checkpoints(result.session_id)
        assert len(checkpoints) == 2
        assert checkpoints[0].phase == "researching"
        assert checkpoints[1].phase == "completed"

    def test_multi_checkpoint_then_done(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_MULTI_CHECKPOINT_THEN_DONE)
        assert result.final_status == "completed"
        assert result.iterations == 4
        checkpoints = mgr.list_checkpoints(result.session_id)
        phases = [c.phase for c in checkpoints]
        assert phases == ["researching", "implementing", "verifying", "completed"]

    def test_wait_then_resume_then_done(self) -> None:
        mgr, wake, result = run_pattern(
            PATTERN_WAIT_THEN_DONE,
            wait_fn=lambda **kw: True,
        )
        assert result.final_status == "completed"
        assert result.iterations == 2
        session = mgr.get_session(result.session_id)
        assert session is not None
        assert session.status == "completed"

    def test_retry_then_done(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_RETRY_THEN_DONE)
        assert result.final_status == "completed"
        assert result.iterations == 3
        checkpoints = mgr.list_checkpoints(result.session_id)
        assert any("retry" in c.summary.lower() for c in checkpoints)

    def test_checkpoint_wait_checkpoint_done(self) -> None:
        mgr, wake, result = run_pattern(
            PATTERN_CHECKPOINT_WAIT_CHECKPOINT_DONE,
            wait_fn=lambda **kw: True,
        )
        assert result.final_status == "completed"
        assert result.iterations == 4

    def test_blocked_terminal(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_BLOCKED_TERMINAL)
        assert result.final_status == "failed_terminal"
        assert result.iterations == 1

    def test_all_phases_checkpoint(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_ALL_CHECKPOINTS)
        assert result.final_status == "completed"
        assert result.iterations == 7
        checkpoints = mgr.list_checkpoints(result.session_id)
        phases = [c.phase for c in checkpoints[:-1]]
        assert phases == [
            "planning",
            "researching",
            "implementing",
            "verifying",
            "repairing",
            "integrating",
        ]

    def test_needs_decision_terminalizes_without_policy(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_NEEDS_DECISION_THEN_DONE)
        assert result.final_status == "human_required"
        assert result.iterations == 1

    def test_needs_decision_retries_with_policy_engine(self) -> None:
        pattern = [
            {
                "outcome": "needs_decision",
                "summary": "unclear scope",
                "decision_required": True,
            },
            {
                "outcome": "needs_decision",
                "summary": "still unclear",
                "decision_required": True,
            },
            make_done("resolved"),
        ]
        mgr, wake, result = run_pattern(pattern, policy_engine_fn=evaluate_policy)
        assert result.final_status == "completed"
        assert result.iterations == 3

    def test_wait_no_wait_fn_still_completes_via_wakeup(self) -> None:
        mgr, wake, result = run_pattern(PATTERN_WAIT_THEN_DONE, wait_fn=None)
        assert result.final_status == "completed"
        assert result.iterations == 2


class TestExecutorOutputToSessionLifecycle:
    def test_marker_output_parsed_and_processed(self) -> None:
        stdout = f"{EXECUTION_CHECKPOINT_MARKER}{json.dumps(make_checkpoint('researching', 'found modules'))}"
        executor_result = parse_executor_output(stdout, "", 0)
        assert executor_result.success is True
        kind = classify_execution_payload(executor_result.payload)
        assert kind == "checkpoint"
        errors = validate_checkpoint_payload(executor_result.payload)
        assert errors == []

    def test_marker_wait_parsed_and_processed(self) -> None:
        stdout = (
            f"{EXECUTION_WAIT_MARKER}{json.dumps(make_wait('timer', 'waiting 5s'))}"
        )
        executor_result = parse_executor_output(stdout, "", 0)
        assert executor_result.success is True
        kind = classify_execution_payload(executor_result.payload)
        assert kind == "wait"
        errors = validate_wait_payload(executor_result.payload)
        assert errors == []

    def test_terminal_result_parsed_and_processed(self) -> None:
        stdout = f"{EXECUTION_RESULT_MARKER}{json.dumps(make_done('task completed'))}"
        executor_result = parse_executor_output(stdout, "", 0)
        assert executor_result.success is True
        assert executor_result.payload["outcome"] == "done"

    def test_full_cycle_marker_to_session_completion(self) -> None:
        marker_outputs = [
            f"{EXECUTION_CHECKPOINT_MARKER}{json.dumps(make_checkpoint('researching', 'step 1'))}",
            f"{EXECUTION_CHECKPOINT_MARKER}{json.dumps(make_checkpoint('implementing', 'step 2'))}",
            f"{EXECUTION_RESULT_MARKER}{json.dumps(make_done('done'))}",
        ]
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(marker_outputs):
                return parse_executor_output(marker_outputs[idx], "", 0)
            return ExecutorResult(success=True, payload=make_done())

        mgr, wake = setup_session_pair()
        session = create_active_session(mgr)
        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
        )
        assert result.final_status == "completed"
        assert result.iterations == 3
        assert call_count["n"] == 3


class TestWakeupEventInjection:
    def test_external_event_fires_wakeup_and_resumes(self) -> None:
        pattern = [
            make_wait("subagent_result", "waiting for subagent"),
            make_done("completed after subagent"),
        ]
        mgr, wake = setup_session_pair()
        session = create_active_session(mgr)
        call_count = {"n": 0}

        def executor_fn(**kwargs: Any) -> ExecutorResult:
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(pattern):
                return ExecutorResult(success=True, payload=pattern[idx])
            return ExecutorResult(success=True, payload=make_done())

        result = run_session_to_completion(
            session_id=session.id,
            session_manager=mgr,
            wakeup_dispatcher=wake,
            executor_fn=executor_fn,
            wait_fn=lambda **kw: True,
        )
        assert result.final_status == "completed"
        assert result.iterations == 2

    def test_fire_wakeup_for_event_with_session_integration(self) -> None:
        mgr, wake = setup_session_pair()
        session = create_active_session(mgr)
        mgr.suspend_session(session.id, waiting_reason="tool_result")
        wake.register_wakeup(
            session_id=session.id,
            work_id="w1",
            wake_type="tool_result",
            wake_condition={"tool": "build"},
        )
        fired = fire_wakeup_for_event(
            wakeup_dispatcher=wake,
            session_manager=mgr,
            session_id=session.id,
            wake_type="tool_result",
        )
        assert fired is True
        updated = mgr.get_session(session.id)
        assert updated is not None
        assert updated.status == "active"
