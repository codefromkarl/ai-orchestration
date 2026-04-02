from __future__ import annotations

from typing import Any, Callable

from taskplane.models import ExecutionSession
from taskplane.session_manager import InMemorySessionManager
from taskplane.session_runtime_loop import (
    ExecutorResult,
    SessionCompletionResult,
    run_session_to_completion,
)
from taskplane.wakeup_dispatcher import InMemoryWakeupDispatcher


def setup_session_pair(
    work_id: str = "w1",
) -> tuple[InMemorySessionManager, InMemoryWakeupDispatcher]:
    return InMemorySessionManager(), InMemoryWakeupDispatcher()


def create_active_session(
    mgr: InMemorySessionManager,
    work_id: str = "w1",
    **kwargs: Any,
) -> ExecutionSession:
    return mgr.create_session(work_id=work_id, **kwargs)


def make_executor_sequence(
    payloads: list[dict[str, Any]],
) -> Callable[..., ExecutorResult]:
    state = {"index": 0}

    def executor_fn(**kwargs: Any) -> ExecutorResult:
        idx = state["index"]
        if idx < len(payloads):
            state["index"] = idx + 1
            return ExecutorResult(success=True, payload=payloads[idx])
        return ExecutorResult(success=True, payload=payloads[-1])

    return executor_fn


def make_checkpoint(
    phase: str = "researching", summary: str = "step"
) -> dict[str, Any]:
    return {
        "execution_kind": "checkpoint",
        "phase": phase,
        "summary": summary,
    }


def make_checkpoint_with_artifacts(
    phase: str = "implementing",
    summary: str = "changes",
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "execution_kind": "checkpoint",
        "phase": phase,
        "summary": summary,
        "artifacts": artifacts or {},
    }


def make_wait(
    wait_type: str = "subagent_result", summary: str = "waiting"
) -> dict[str, Any]:
    return {
        "execution_kind": "wait",
        "wait_type": wait_type,
        "summary": summary,
        "resume_hint": "resume after wait",
    }


def make_done(summary: str = "completed") -> dict[str, Any]:
    return {"outcome": "done", "summary": summary}


def make_blocked(summary: str = "blocked") -> dict[str, Any]:
    return {"outcome": "blocked", "summary": summary}


def make_needs_decision(summary: str = "needs decision") -> dict[str, Any]:
    return {"outcome": "needs_decision", "summary": summary, "decision_required": True}


def make_retry_intent(failure_reason: str = "timeout") -> dict[str, Any]:
    return {
        "execution_kind": "retry_intent",
        "failure_reason": failure_reason,
        "summary": f"retrying after {failure_reason}",
    }


PATTERN_CHECKPOINT_THEN_DONE: list[dict[str, Any]] = [
    make_checkpoint("researching", "found 3 modules"),
    make_done("task completed"),
]

PATTERN_MULTI_CHECKPOINT_THEN_DONE: list[dict[str, Any]] = [
    make_checkpoint("researching", "found 3 modules"),
    make_checkpoint("implementing", "wrote fix"),
    make_checkpoint("verifying", "tests pass"),
    make_done("task completed"),
]

PATTERN_WAIT_THEN_DONE: list[dict[str, Any]] = [
    make_wait("subagent_result", "waiting for subagent"),
    make_done("task completed after wait"),
]

PATTERN_RETRY_THEN_DONE: list[dict[str, Any]] = [
    make_retry_intent("timeout"),
    make_checkpoint("researching", "retry progress"),
    make_done("completed after retry"),
]

PATTERN_CHECKPOINT_WAIT_CHECKPOINT_DONE: list[dict[str, Any]] = [
    make_checkpoint("researching", "initial research"),
    make_wait("tool_result", "waiting for build"),
    make_checkpoint("implementing", "building after wait"),
    make_done("completed"),
]

PATTERN_NEEDS_DECISION_THEN_DONE: list[dict[str, Any]] = [
    make_needs_decision("need approval for scope change"),
    make_done("approved and completed"),
]

PATTERN_BLOCKED_TERMINAL: list[dict[str, Any]] = [
    make_blocked("cannot proceed: missing dependency"),
]

PATTERN_ALL_CHECKPOINTS: list[dict[str, Any]] = [
    make_checkpoint("planning", "plan"),
    make_checkpoint("researching", "research"),
    make_checkpoint("implementing", "implement"),
    make_checkpoint("verifying", "verify"),
    make_checkpoint("repairing", "repair"),
    make_checkpoint("integrating", "integrate"),
    make_done("all phases done"),
]


def run_pattern(
    pattern: list[dict[str, Any]],
    *,
    work_id: str = "w1",
    max_iterations: int = 50,
    policy_engine_fn: Callable[..., Any] | None = None,
    wait_fn: Callable[..., bool] | None = None,
) -> tuple[InMemorySessionManager, InMemoryWakeupDispatcher, SessionCompletionResult]:
    mgr, wake = setup_session_pair(work_id)
    session = create_active_session(mgr, work_id)
    executor = make_executor_sequence(pattern)
    result = run_session_to_completion(
        session_id=session.id,
        session_manager=mgr,
        wakeup_dispatcher=wake,
        executor_fn=executor,
        policy_engine_fn=policy_engine_fn,
        max_iterations=max_iterations,
        wait_fn=wait_fn,
    )
    return mgr, wake, result
