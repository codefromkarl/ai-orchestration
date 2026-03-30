"""Example: run a long session with checkpoint/wait lifecycle using mock executor."""

from __future__ import annotations

import json
from typing import Any

from stardrifter_orchestration_mvp.policy_engine import evaluate_policy
from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager
from stardrifter_orchestration_mvp.session_runtime_loop import (
    ExecutorResult,
    run_session_to_completion,
)
from stardrifter_orchestration_mvp.wakeup_dispatcher import InMemoryWakeupDispatcher


def make_multi_step_executor():
    """Simulates a long task that goes through multiple phases."""
    step = {"n": 0}

    def executor_fn(**kwargs: Any) -> ExecutorResult:
        n = step["n"]
        step["n"] += 1

        # Phase 1: Research
        if n == 0:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "researching",
                    "summary": "Found 3 candidate modules in auth layer",
                    "artifacts": {"files": ["auth/service.py", "auth/models.py"]},
                    "next_action_hint": "Examine auth/service.py for the fix",
                },
            )
        # Phase 2: More research
        if n == 1:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "researching",
                    "summary": "Identified root cause: missing null check in validate_token()",
                    "artifacts": {"line": 142, "function": "validate_token"},
                    "next_action_hint": "Implement the null check fix",
                },
            )
        # Phase 3: Implement
        if n == 2:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "implementing",
                    "summary": "Added null check in validate_token(), writing tests",
                    "artifacts": {
                        "changed_files": ["auth/service.py", "tests/test_auth.py"]
                    },
                    "next_action_hint": "Run verifier to confirm tests pass",
                },
            )
        # Phase 4: Verify
        if n == 3:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "verifying",
                    "summary": "All 47 tests pass, 0 failures",
                    "next_action_hint": "Mark task as done",
                },
            )
        # Phase 5: Complete
        return ExecutorResult(
            success=True,
            payload={
                "outcome": "done",
                "summary": "Fixed null check in auth/service.py validate_token(). All tests pass.",
            },
        )

    return executor_fn


def make_executor_with_wait():
    """Simulates a task that needs to wait for an external tool."""
    step = {"n": 0}

    def executor_fn(**kwargs: Any) -> ExecutorResult:
        n = step["n"]
        step["n"] += 1

        if n == 0:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "researching",
                    "summary": "Identified the module to fix",
                    "next_action_hint": "Build project to confirm current state",
                },
            )
        if n == 1:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "wait",
                    "wait_type": "tool_result",
                    "summary": "Waiting for build system to finish compiling",
                    "resume_hint": "Continue with implementation after build completes",
                },
            )
        if n == 2:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "implementing",
                    "summary": "Build passed, implementing the fix",
                    "next_action_hint": "Run tests",
                },
            )
        return ExecutorResult(
            success=True,
            payload={"outcome": "done", "summary": "Fix implemented and verified"},
        )

    return executor_fn


def make_executor_with_retry():
    """Simulates a task that needs policy-driven retry."""
    step = {"n": 0}

    def executor_fn(**kwargs: Any) -> ExecutorResult:
        n = step["n"]
        step["n"] += 1

        if n == 0:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "researching",
                    "summary": "Research complete",
                },
            )
        if n == 1:
            return ExecutorResult(
                success=True,
                payload={
                    "outcome": "needs_decision",
                    "summary": "Unclear whether to refactor or patch",
                    "decision_required": True,
                },
            )
        if n == 2:
            return ExecutorResult(
                success=True,
                payload={
                    "execution_kind": "checkpoint",
                    "phase": "implementing",
                    "summary": "Proceeding with patch approach (policy: retry with narrowed scope)",
                },
            )
        return ExecutorResult(
            success=True,
            payload={"outcome": "done", "summary": "Patched successfully"},
        )

    return executor_fn


def run_demo(executor_fn, *, label: str, wait_fn=None) -> None:
    mgr = InMemorySessionManager()
    wake = InMemoryWakeupDispatcher()
    session = mgr.create_session(work_id="demo-task-1", current_phase="researching")

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"  Session ID: {session.id}")
    print(f"  Initial phase: {session.current_phase}")
    print(f"{'=' * 60}\n")

    result = run_session_to_completion(
        session_id=session.id,
        session_manager=mgr,
        wakeup_dispatcher=wake,
        executor_fn=executor_fn,
        policy_engine_fn=evaluate_policy,
        wait_fn=wait_fn,
    )

    # Print checkpoints
    checkpoints = mgr.list_checkpoints(session.id)
    print(f"Checkpoints ({len(checkpoints)}):")
    for i, ckpt in enumerate(checkpoints, 1):
        print(
            f"  [{i}] phase={ckpt.phase} index={ckpt.phase_index} summary={ckpt.summary}"
        )
        if ckpt.next_action_hint:
            print(f"      next_action={ckpt.next_action_hint}")

    # Print final state
    final_session = mgr.get_session(session.id)
    print(f"\nFinal status: {result.final_status}")
    print(f"Iterations: {result.iterations}")
    print(f"Last action: {result.result.action if result.result else 'none'}")
    print(f"Session status: {final_session.status if final_session else 'unknown'}")


if __name__ == "__main__":
    print("Long Session Execution Demo")
    print("=" * 60)

    # Scenario 1: Multi-phase checkpoint then done
    run_demo(
        make_multi_step_executor(), label="Scenario 1: Multi-phase checkpoint → done"
    )

    # Scenario 2: Wait for external tool then resume
    run_demo(
        make_executor_with_wait(),
        label="Scenario 2: Checkpoint → wait → resume → done",
        wait_fn=lambda **kw: True,
    )

    # Scenario 3: Needs decision with policy retry
    run_demo(
        make_executor_with_retry(),
        label="Scenario 3: Needs decision → policy retry → done",
    )

    print("\n" + "=" * 60)
    print("All scenarios completed.")
