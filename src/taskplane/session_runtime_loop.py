from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from .event_log import (
    EventEnvelope,
    EventLogRecorder,
    build_policy_resolution_event,
    build_session_checkpoint_event,
    build_wakeup_event,
)
from .models import (
    SESSION_TERMINAL_STATUSES,
    SESSION_WAITING_STATUSES,
    ExecutionCheckpoint,
    ExecutionSession,
    SessionStatus,
)
from .session_protocol import (
    EXECUTION_KIND_CHECKPOINT,
    EXECUTION_KIND_RETRY_INTENT,
    EXECUTION_KIND_TERMINAL,
    EXECUTION_KIND_UNEXPECTED,
    EXECUTION_KIND_WAIT,
    parse_executor_payload,
)
from .protocols import (
    SessionManagerProtocol,
    SessionTurnRequest,
    WakeupDispatcherProtocol,
)


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


ResumeContextBuilder = Callable[[ExecutionSession], str]


def _invoke_session_executor(
    executor_fn: Any,
    *,
    request: SessionTurnRequest,
) -> Any:
    run_turn = getattr(executor_fn, "run_turn", None)
    if callable(run_turn):
        return run_turn(request)
    return executor_fn(
        session_id=request.session_id,
        work_id=request.work_id,
        resume_context=request.resume_context,
        current_phase=request.current_phase,
    )


def _normalize_executor_result(raw_result: Any) -> ExecutorResult:
    if not isinstance(raw_result, ExecutorResult):
        return ExecutorResult(
            success=False,
            payload={
                "outcome": "blocked",
                "reason_code": "invalid-executor-result",
                "summary": "executor did not return an ExecutorResult",
            },
            exit_code=-1,
        )

    if isinstance(raw_result.payload, dict):
        return raw_result

    return ExecutorResult(
        success=False,
        payload={
            "outcome": "blocked",
            "reason_code": "invalid-executor-payload",
            "summary": "executor returned a non-dict payload",
        },
        exit_code=raw_result.exit_code,
    )


def _record_policy_resolution(
    *,
    session_manager: SessionManagerProtocol,
    session: ExecutionSession,
    evidence_json: dict[str, Any],
    resolution: str,
    risk_level: str,
    trigger_reason: str,
    resolution_detail_json: dict[str, Any] | None = None,
    applied: bool = False,
) -> None:
    session_manager.record_policy_resolution(
        session_id=session.id,
        work_id=session.work_id,
        risk_level=risk_level,
        trigger_reason=trigger_reason,
        evidence_json=evidence_json,
        resolution=resolution,
        resolution_detail_json=resolution_detail_json,
        applied=applied,
    )


def _record_event(
    event_recorder: EventLogRecorder | None, event: EventEnvelope
) -> None:
    if event_recorder is None:
        return
    try:
        event_recorder.record(event)
    except Exception:
        pass


def _record_checkpoint_event(
    *,
    event_recorder: EventLogRecorder | None,
    session: ExecutionSession,
    checkpoint: ExecutionCheckpoint | None,
) -> None:
    if event_recorder is None or checkpoint is None:
        return
    _record_event(
        event_recorder,
        build_session_checkpoint_event(session=session, checkpoint=checkpoint),
    )


def run_session_iteration(
    *,
    session: ExecutionSession,
    session_manager: SessionManagerProtocol,
    wakeup_dispatcher: WakeupDispatcherProtocol,
    executor_fn: Any,
    event_recorder: EventLogRecorder | None = None,
    resume_context: str | None = None,
    resume_context_builder: ResumeContextBuilder | None = None,
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

    ctx = resume_context.strip() if isinstance(resume_context, str) else resume_context
    if not ctx:
        if resume_context_builder is not None:
            try:
                ctx = resume_context_builder(session).strip()
            except Exception:
                ctx = None
        if not ctx:
            ctx = session_manager.build_resume_context(session.id)
    request = SessionTurnRequest(
        session_id=session.id,
        work_id=session.work_id,
        resume_context=ctx,
        current_phase=session.current_phase,
    )

    try:
        result = _normalize_executor_result(
            _invoke_session_executor(
                executor_fn,
                request=request,
            )
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

    parsed = parse_executor_payload(result.payload)

    if parsed.kind == EXECUTION_KIND_CHECKPOINT and parsed.checkpoint is not None:
        checkpoint = parsed.checkpoint
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=checkpoint.phase or session.current_phase,
            summary=checkpoint.summary or "checkpoint",
            artifacts=checkpoint.artifacts,
            tool_state=checkpoint.tool_state,
            subtasks=checkpoint.subtasks,
            next_action_hint=checkpoint.next_action_hint,
            next_action_params=checkpoint.next_action_params,
        )
        updated_session = session_manager.update_session_phase(
            session.id, checkpoint.phase or session.current_phase
        )
        _record_checkpoint_event(
            event_recorder=event_recorder,
            session=updated_session or session,
            checkpoint=ckpt,
        )
        return SessionIterationResult(
            session_id=session.id,
            action="checkpoint",
            checkpoint=ckpt,
        )

    if parsed.kind == EXECUTION_KIND_WAIT and parsed.wait is not None:
        wait = parsed.wait
        session_manager.suspend_session(
            session.id,
            waiting_reason=wait.wait_type or "timer",
            wake_condition=parsed.raw_payload,
        )
        wakeup_dispatcher.register_wakeup(
            session_id=session.id,
            work_id=session.work_id,
            wake_type=wait.wait_type or "timer",
            wake_condition=parsed.raw_payload,
        )
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"waiting: {wait.summary or 'waiting'}",
            tool_state={"wait_type": wait.wait_type or "timer"},
            next_action_hint=wait.resume_hint,
        )
        return SessionIterationResult(
            session_id=session.id,
            action="suspended",
            checkpoint=ckpt,
        )

    if parsed.kind == EXECUTION_KIND_RETRY_INTENT and parsed.retry_intent is not None:
        retry_intent = parsed.retry_intent
        next_action_hint = str(
            retry_intent.resume_hint or retry_intent.retry_prompt_template or "retry"
        )
        failure_context = {"failure_reason": retry_intent.failure_reason}
        if retry_intent.retry_prompt_template:
            failure_context["retry_prompt_template"] = retry_intent.retry_prompt_template
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"retry: {retry_intent.summary or 'retry'}",
            failure_context=failure_context,
            next_action_hint=next_action_hint,
        )
        _record_checkpoint_event(
            event_recorder=event_recorder,
            session=session,
            checkpoint=ckpt,
        )
        _record_event(
            event_recorder,
            build_policy_resolution_event(
                session=session,
                action="retry_intent",
                resolution="retry_strategy",
                trigger_reason=retry_intent.failure_reason,
                applied=True,
                phase=session.current_phase,
                summary=retry_intent.summary or "retry",
                detail={
                    "retry_prompt_template": retry_intent.retry_prompt_template,
                    "source": "retry_intent",
                },
            ),
        )
        return SessionIterationResult(
            session_id=session.id,
            action="retry",
            checkpoint=ckpt,
        )

    if parsed.kind == EXECUTION_KIND_TERMINAL and parsed.terminal is not None:
        terminal = parsed.terminal
        outcome = terminal.outcome
        if outcome in {"done", "already_satisfied"}:
            session_manager.update_session_status(session.id, "completed")
            ckpt = session_manager.append_checkpoint(
                session.id,
                phase="completed",
                summary=terminal.summary or f"completed with {outcome}",
            )
            return SessionIterationResult(
                session_id=session.id,
                action="completed",
                checkpoint=ckpt,
            )

        if outcome in {"blocked", "needs_decision"}:
            policy_resolution_recorded = False
            if policy_engine_fn is not None:
                try:
                    policy = policy_engine_fn(
                        session=session,
                        checkpoint=session_manager.get_latest_checkpoint(session.id),
                        failure_context=parsed.raw_payload,
                        attempt_index=session.attempt_index,
                    )
                except Exception:
                    policy = None
                else:
                    policy_resolution = str(policy.resolution or "").strip().lower()
                    policy_risk_level = str(policy.risk_level or "").strip().lower()
                    policy_trigger_reason = str(policy.reason or outcome)
                    policy_detail = policy.detail if policy.detail is not None else None
                    if policy_resolution == "retry_strategy":
                        ckpt = session_manager.append_checkpoint(
                            session.id,
                            phase=session.current_phase,
                            summary=f"policy: {policy.reason}",
                            failure_context=parsed.raw_payload,
                            next_action_hint=policy.detail.get("strategy", "retry")
                            if policy.detail
                            else "retry",
                        )
                        _record_checkpoint_event(
                            event_recorder=event_recorder,
                            session=session,
                            checkpoint=ckpt,
                        )
                        _record_policy_resolution(
                            session_manager=session_manager,
                            session=session,
                            evidence_json=parsed.raw_payload,
                            resolution=policy_resolution,
                            risk_level=policy_risk_level or "medium",
                            trigger_reason=policy_trigger_reason,
                            resolution_detail_json=policy_detail,
                            applied=True,
                        )
                        _record_event(
                            event_recorder,
                            build_policy_resolution_event(
                                session=session,
                                action="policy_retry",
                                resolution="retry_strategy",
                                trigger_reason=policy_trigger_reason,
                                applied=True,
                                phase=session.current_phase,
                                summary=f"policy: {policy.reason}",
                                detail=policy_detail,
                            ),
                        )
                        return SessionIterationResult(
                            session_id=session.id,
                            action="policy_retry",
                            checkpoint=ckpt,
                        )
                    if policy_resolution == "auto_resolve":
                        ckpt = session_manager.append_checkpoint(
                            session.id,
                            phase=session.current_phase,
                            summary=f"auto_resolve: {policy.reason}",
                            failure_context=parsed.raw_payload,
                            next_action_hint="auto_resolve",
                        )
                        _record_checkpoint_event(
                            event_recorder=event_recorder,
                            session=session,
                            checkpoint=ckpt,
                        )
                        _record_policy_resolution(
                            session_manager=session_manager,
                            session=session,
                            evidence_json=parsed.raw_payload,
                            resolution=policy_resolution,
                            risk_level=policy_risk_level or "low",
                            trigger_reason=policy_trigger_reason,
                            resolution_detail_json=policy_detail,
                            applied=True,
                        )
                        _record_event(
                            event_recorder,
                            build_policy_resolution_event(
                                session=session,
                                action="auto_resolve",
                                resolution="auto_resolve",
                                trigger_reason=policy_trigger_reason,
                                applied=True,
                                phase=session.current_phase,
                                summary=f"auto_resolve: {policy.reason}",
                                detail=policy_detail,
                            ),
                        )
                        return SessionIterationResult(
                            session_id=session.id,
                            action="auto_resolve",
                            checkpoint=ckpt,
                        )
                    if policy_resolution == "human_required":
                        status: SessionStatus = (
                            "human_required"
                            if outcome == "needs_decision"
                            else "failed_terminal"
                        )
                        status_session = session_manager.update_session_status(
                            session.id, status
                        )
                        ckpt = session_manager.append_checkpoint(
                            session.id,
                            phase=session.current_phase,
                            summary=terminal.summary or outcome,
                            failure_context=parsed.raw_payload,
                            next_action_hint="human_review"
                            if outcome == "needs_decision"
                            else "investigate",
                        )
                        _record_checkpoint_event(
                            event_recorder=event_recorder,
                            session=status_session or session,
                            checkpoint=ckpt,
                        )
                        _record_policy_resolution(
                            session_manager=session_manager,
                            session=session,
                            evidence_json=parsed.raw_payload,
                            resolution=policy_resolution,
                            risk_level=policy_risk_level or "high",
                            trigger_reason=policy_trigger_reason,
                            resolution_detail_json=policy_detail,
                            applied=outcome == "needs_decision",
                        )
                        _record_event(
                            event_recorder,
                            build_policy_resolution_event(
                                session=session,
                                action="terminalized",
                                resolution="human_required",
                                trigger_reason=policy_trigger_reason,
                                applied=outcome == "needs_decision",
                                phase=session.current_phase,
                                summary=terminal.summary or outcome,
                                detail=policy_detail,
                            ),
                        )
                        policy_resolution_recorded = True
                    elif policy_resolution:
                        status = (
                            "human_required"
                            if outcome == "needs_decision"
                            else "failed_terminal"
                        )
                        status_session = session_manager.update_session_status(
                            session.id, status
                        )
                        ckpt = session_manager.append_checkpoint(
                            session.id,
                            phase=session.current_phase,
                            summary=terminal.summary or outcome,
                            failure_context=parsed.raw_payload,
                            next_action_hint="human_review"
                            if outcome == "needs_decision"
                            else "investigate",
                        )
                        _record_checkpoint_event(
                            event_recorder=event_recorder,
                            session=status_session or session,
                            checkpoint=ckpt,
                        )
                        _record_policy_resolution(
                            session_manager=session_manager,
                            session=session,
                            evidence_json=parsed.raw_payload,
                            resolution=policy_resolution,
                            risk_level=policy_risk_level or "high",
                            trigger_reason=policy_trigger_reason,
                            resolution_detail_json=policy_detail,
                            applied=False,
                        )
                        _record_event(
                            event_recorder,
                            build_policy_resolution_event(
                                session=session,
                                action="terminalized",
                                resolution=(
                                    "human_required"
                                    if outcome == "needs_decision"
                                    else "failed_terminal"
                                ),
                                trigger_reason=policy_trigger_reason,
                                applied=False,
                                phase=session.current_phase,
                                summary=terminal.summary or outcome,
                                detail=policy_detail,
                            ),
                        )
                        policy_resolution_recorded = True
            if not policy_resolution_recorded:
                status: SessionStatus = (
                    "human_required" if outcome == "needs_decision" else "failed_terminal"
                )
                status_session = session_manager.update_session_status(session.id, status)
                ckpt = session_manager.append_checkpoint(
                    session.id,
                    phase=session.current_phase,
                    summary=terminal.summary or outcome,
                    failure_context=parsed.raw_payload,
                    next_action_hint="human_review"
                    if outcome == "needs_decision"
                    else "investigate",
                )
                _record_checkpoint_event(
                    event_recorder=event_recorder,
                    session=status_session or session,
                    checkpoint=ckpt,
                )
                _record_policy_resolution(
                    session_manager=session_manager,
                    session=session,
                    evidence_json=parsed.raw_payload,
                    resolution=(
                        "human_required"
                        if outcome == "needs_decision"
                        else "failed_terminal"
                    ),
                    risk_level="high",
                    trigger_reason=parsed.raw_payload.get("summary") or outcome,
                    resolution_detail_json={
                        "outcome": outcome,
                        "source": "fallback",
                    },
                    applied=True,
                )
                _record_event(
                    event_recorder,
                    build_policy_resolution_event(
                        session=session,
                        action="terminalized",
                        resolution=(
                            "human_required"
                            if outcome == "needs_decision"
                            else "failed_terminal"
                        ),
                        trigger_reason=parsed.raw_payload.get("summary") or outcome,
                        applied=True,
                        phase=session.current_phase,
                        summary=terminal.summary or outcome,
                        detail={
                            "outcome": outcome,
                            "source": "fallback",
                        },
                    ),
                )
            return SessionIterationResult(
                session_id=session.id,
                action="terminalized",
                checkpoint=ckpt,
            )

    if parsed.kind == EXECUTION_KIND_UNEXPECTED:
        ckpt = session_manager.append_checkpoint(
            session.id,
            phase=session.current_phase,
            summary=f"unexpected payload: {json.dumps(parsed.raw_payload, ensure_ascii=False)[:200]}",
            failure_context={"payload": parsed.raw_payload},
            next_action_hint="investigate",
        )
        return SessionIterationResult(
            session_id=session.id,
            action="unexpected",
            checkpoint=ckpt,
            error=f"unexpected payload reason={parsed.unexpected_reason}",
        )

    ckpt = session_manager.append_checkpoint(
        session.id,
        phase=session.current_phase,
        summary=f"unexpected payload: {json.dumps(parsed.raw_payload, ensure_ascii=False)[:200]}",
        failure_context={"payload": parsed.raw_payload},
        next_action_hint="investigate",
    )
    return SessionIterationResult(
        session_id=session.id,
        action="unexpected",
        checkpoint=ckpt,
        error=f"unexpected payload kind={parsed.kind}",
    )


def process_session_wakeups(
    *,
    session_manager: SessionManagerProtocol,
    wakeup_dispatcher: WakeupDispatcherProtocol,
    event_recorder: EventLogRecorder | None = None,
) -> list[str]:
    fired_session_ids = wakeup_dispatcher.process_fireable()
    resumed: list[str] = []
    fired_counts = Counter(fired_session_ids)
    for sid in fired_session_ids:
        session = session_manager.resume_session(sid)
        if session is not None and session.status == "active":
            resumed.append(sid)
            _record_event(
                event_recorder,
                build_wakeup_event(
                    session=session,
                    action="resumed",
                    summary="session resumed after wakeup dispatch",
                    detail={
                        "source": "process_session_wakeups",
                        "wakeup_count": fired_counts[sid],
                    },
                ),
            )
    return resumed


def fire_wakeup_for_event(
    *,
    wakeup_dispatcher: WakeupDispatcherProtocol,
    session_manager: SessionManagerProtocol,
    session_id: str,
    wake_type: str,
    event_data: dict[str, Any] | None = None,
    event_recorder: EventLogRecorder | None = None,
) -> bool:
    fired = False
    for wakeup in wakeup_dispatcher.list_by_session(session_id):
        if wakeup.status != "pending":
            continue
        if wakeup.wake_type == wake_type:
            result = wakeup_dispatcher.fire_wakeup(wakeup.id)
            if result is not None:
                resumed_session = session_manager.resume_session(session_id)
                if resumed_session is not None and resumed_session.status == "active":
                    _record_event(
                        event_recorder,
                        build_wakeup_event(
                            session=resumed_session,
                            action="resumed",
                            wakeup_type=wakeup.wake_type,
                            summary="session resumed after wakeup fire",
                            detail={
                                "source": "fire_wakeup_for_event",
                                "wakeup_id": wakeup.id,
                                "wake_condition": wakeup.wake_condition,
                                "event_data": event_data,
                            },
                        ),
                    )
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
    session_manager: SessionManagerProtocol,
    wakeup_dispatcher: WakeupDispatcherProtocol,
    executor_fn: Any,
    event_recorder: EventLogRecorder | None = None,
    resume_context_builder: ResumeContextBuilder | None = None,
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
            event_recorder=event_recorder,
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
            event_recorder=event_recorder,
            resume_context_builder=resume_context_builder,
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
