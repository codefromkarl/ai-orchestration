from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from .models import (
    SESSION_TERMINAL_STATUSES,
    SESSION_WAITING_STATUSES,
    ExecutionCheckpoint,
    ExecutionSession,
    SessionStatus,
)
from .session_manager import InMemorySessionManager
from .wakeup_dispatcher import InMemoryWakeupDispatcher


@dataclass(frozen=True)
class SessionIterationResult:
    session_id: str
    action: str
    checkpoint: ExecutionCheckpoint | None = None
    error: str | None = None


@dataclass(frozen=True)
class ExecutorResult:
    success: bool
    payload: dict[str, Any]
    exit_code: int = 0


def run_session_iteration(
    *,
    session: ExecutionSession,
    session_manager: InMemorySessionManager,
    wakeup_dispatcher: InMemoryWakeupDispatcher,
    executor_fn: Callable[..., ExecutorResult],
    resume_context: str | None = None,
    policy_engine_fn: Callable[..., Any] | None = None,
) -> SessionIterationResult:
    if session.status in SESSION_TERMINAL_STATUSES:
        return SessionIterationResult(
            session_id=session.id,
            action="skip",
            error=f"session {session.id} is terminal ({session.status})",
        )

    if session.status in SESSION_WAITING_STATUSES:
        return SessionIterationResult(
            session_id=session.id,
            action="skip",
            error=f"session {session.id} is waiting ({session.status})",
        )

    ctx = resume_context or session_manager.build_resume_context(session.id)

    try:
        result = executor_fn(
            session_id=session.id,
            work_id=session.work_id,
            resume_context=ctx,
            current_phase=session.current_phase,
        )
    except Exception as exc:
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"executor failed: {exc}",
            failure_context={"error": str(exc)},
            next_action_hint="retry",
        )
        return SessionIterationResult(
            session_id=session.id,
            action="executor_error",
            checkpoint=ckpt,
            error=str(exc),
        )

    payload = result.payload
    kind = str(payload.get("execution_kind") or "").strip().lower()

    if kind == "checkpoint":
        phase = str(payload.get("phase") or session.current_phase)
        summary = str(payload.get("summary") or "checkpoint")
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=phase,
            summary=summary,
            artifacts=payload.get("artifacts"),
            tool_state=payload.get("tool_state"),
            subtasks=payload.get("subtasks"),
            next_action_hint=payload.get("next_action_hint"),
        )
        session_manager.update_session_phase(session.id, phase)
        return SessionIterationResult(
            session_id=session.id,
            action="checkpoint",
            checkpoint=ckpt,
        )

    if kind == "wait":
        wait_type = str(payload.get("wait_type") or "timer")
        summary = str(payload.get("summary") or "waiting")
        session_manager.suspend_session(
            session.id,
            waiting_reason=wait_type,
            wake_condition=payload,
        )
        wakeup_dispatcher.register_wakeup(
            session_id=session.id,
            work_id=session.work_id,
            wake_type=wait_type,
            wake_condition=payload,
        )
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"waiting: {summary}",
            tool_state={"wait_type": wait_type},
            next_action_hint=payload.get("resume_hint"),
        )
        return SessionIterationResult(
            session_id=session.id,
            action="suspended",
            checkpoint=ckpt,
        )

    if kind == "retry_intent":
        failure_reason = str(payload.get("failure_reason") or "unknown")
        summary = str(payload.get("summary") or "retry")
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"retry: {summary}",
            failure_context={"failure_reason": failure_reason},
            next_action_hint="retry",
        )
        return SessionIterationResult(
            session_id=session.id,
            action="retry",
            checkpoint=ckpt,
        )

    outcome = str(payload.get("outcome") or "").strip().lower()
    if outcome in {"done", "already_satisfied"}:
        session_manager.update_session_status(session.id, "completed")
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase="completed",
            summary=payload.get("summary") or f"completed with {outcome}",
        )
        return SessionIterationResult(
            session_id=session.id,
            action="completed",
            checkpoint=ckpt,
        )

    if outcome in {"blocked", "needs_decision"}:
        if policy_engine_fn is not None:
            try:
                policy = policy_engine_fn(
                    session=session,
                    checkpoint=session_manager.get_latest_checkpoint(session.id),
                    failure_context=payload,
                    attempt_index=session.attempt_index,
                )
                if policy.resolution == "retry_strategy":
                    ckpt = session_manager.append_checkpoint(
                        session.id,
                        phase=session.current_phase,
                        summary=f"policy: {policy.reason}",
                        failure_context=payload,
                        next_action_hint=policy.detail.get("strategy", "retry")
                        if policy.detail
                        else "retry",
                    )
                    return SessionIterationResult(
                        session_id=session.id,
                        action="policy_retry",
                        checkpoint=ckpt,
                    )
                if policy.resolution == "auto_resolve":
                    ckpt = session_manager.append_checkpoint(
                        session.id,
                        phase=session.current_phase,
                        summary=f"auto_resolve: {policy.reason}",
                        failure_context=payload,
                        next_action_hint="auto_resolve",
                    )
                    return SessionIterationResult(
                        session_id=session.id,
                        action="auto_resolve",
                        checkpoint=ckpt,
                    )
            except Exception:
                pass
        status: SessionStatus = (
            "human_required" if outcome == "needs_decision" else "failed_terminal"
        )
        session_manager.update_session_status(session.id, status)
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=payload.get("summary") or outcome,
            failure_context=payload,
            next_action_hint="human_review"
            if outcome == "needs_decision"
            else "investigate",
        )
        return SessionIterationResult(
            session_id=session.id,
            action="terminalized",
            checkpoint=ckpt,
        )

    ckpt = session_manager.append_checkpoint(
        session.id,
        phase=session.current_phase,
        summary=f"unexpected payload: {json.dumps(payload, ensure_ascii=False)[:200]}",
        failure_context={"payload": payload},
        next_action_hint="investigate",
    )
    return SessionIterationResult(
        session_id=session.id,
        action="unexpected",
        checkpoint=ckpt,
        error=f"unexpected payload kind={kind} outcome={outcome}",
    )


def process_session_wakeups(
    *,
    session_manager: InMemorySessionManager,
    wakeup_dispatcher: InMemoryWakeupDispatcher,
) -> list[str]:
    fired_session_ids = wakeup_dispatcher.process_fireable()
    resumed: list[str] = []
    for sid in fired_session_ids:
        session = session_manager.resume_session(sid)
        if session is not None and session.status == "active":
            resumed.append(sid)
    return resumed


def fire_wakeup_for_event(
    *,
    wakeup_dispatcher: InMemoryWakeupDispatcher,
    session_manager: InMemorySessionManager,
    session_id: str,
    wake_type: str,
    event_data: dict[str, Any] | None = None,
) -> bool:
    fired = False
    for wakeup in wakeup_dispatcher.list_by_session(session_id):
        if wakeup.status != "pending":
            continue
        if wakeup.wake_type == wake_type:
            result = wakeup_dispatcher.fire_wakeup(wakeup.id)
            if result is not None:
                session_manager.resume_session(session_id)
                fired = True
    return fired


@dataclass(frozen=True)
class SessionCompletionResult:
    session_id: str
    final_status: str
    iterations: int
    result: SessionIterationResult | None = None


def run_session_to_completion(
    *,
    session_id: str,
    session_manager: InMemorySessionManager,
    wakeup_dispatcher: InMemoryWakeupDispatcher,
    executor_fn: Callable[..., ExecutorResult],
    policy_engine_fn: Callable[..., Any] | None = None,
    max_iterations: int = 50,
    wait_fn: Callable[..., bool] | None = None,
) -> SessionCompletionResult:
    iterations = 0
    last_result: SessionIterationResult | None = None
    while iterations < max_iterations:
        session = session_manager.get_session(session_id)
        if session is None:
            return SessionCompletionResult(
                session_id=session_id,
                final_status="not_found",
                iterations=iterations,
                result=last_result,
            )
        if session.status in SESSION_TERMINAL_STATUSES:
            return SessionCompletionResult(
                session_id=session_id,
                final_status=session.status,
                iterations=iterations,
                result=last_result,
            )
        process_session_wakeups(
            session_manager=session_manager,
            wakeup_dispatcher=wakeup_dispatcher,
        )
        session = session_manager.get_session(session_id)
        if session is None:
            continue
        if session.status in SESSION_WAITING_STATUSES:
            if wait_fn is not None:
                can_continue = wait_fn(session_id=session_id, session=session)
                if can_continue:
                    session_manager.resume_session(session_id)
                    session = session_manager.get_session(session_id)
                    if session is None:
                        continue
                else:
                    return SessionCompletionResult(
                        session_id=session_id,
                        final_status=session.status,
                        iterations=iterations,
                        result=last_result,
                    )
            else:
                return SessionCompletionResult(
                    session_id=session_id,
                    final_status=session.status,
                    iterations=iterations,
                    result=last_result,
                )
        result = run_session_iteration(
            session=session,
            session_manager=session_manager,
            wakeup_dispatcher=wakeup_dispatcher,
            executor_fn=executor_fn,
            policy_engine_fn=policy_engine_fn,
        )
        last_result = result
        iterations += 1
        if result.action in {"completed", "terminalized"}:
            break
        if result.action == "skip":
            break
    final_session = session_manager.get_session(session_id)
    return SessionCompletionResult(
        session_id=session_id,
        final_status=final_session.status if final_session else "unknown",
        iterations=iterations,
        result=last_result,
    )
