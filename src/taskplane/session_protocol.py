from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .models import ExecutionSession
from .protocols import SessionManagerProtocol, WakeupDispatcherProtocol

EXECUTION_KIND_CHECKPOINT = "checkpoint"
EXECUTION_KIND_WAIT = "wait"
EXECUTION_KIND_RETRY_INTENT = "retry_intent"
EXECUTION_KIND_TERMINAL = "terminal"
EXECUTION_KIND_UNEXPECTED = "unexpected"

SESSION_OUTCOME_DONE = "done"
SESSION_OUTCOME_ALREADY_SATISFIED = "already_satisfied"
SESSION_OUTCOME_BLOCKED = "blocked"
SESSION_OUTCOME_NEEDS_DECISION = "needs_decision"

VALID_EXECUTION_KINDS: tuple[str, ...] = (
    EXECUTION_KIND_CHECKPOINT,
    EXECUTION_KIND_WAIT,
    EXECUTION_KIND_RETRY_INTENT,
    EXECUTION_KIND_TERMINAL,
)

VALID_SESSION_OUTCOMES: tuple[str, ...] = (
    SESSION_OUTCOME_DONE,
    SESSION_OUTCOME_ALREADY_SATISFIED,
    SESSION_OUTCOME_BLOCKED,
    SESSION_OUTCOME_NEEDS_DECISION,
)

REASON_CODE_INVALID_EXECUTOR_PAYLOAD = "invalid-executor-payload"
REASON_CODE_MISSING_EXECUTION_KIND = "missing-execution-kind"
REASON_CODE_MISSING_SESSION_OUTCOME = "missing-session-outcome"
REASON_CODE_UNEXPECTED_SESSION_PAYLOAD = "unexpected-session-payload"

SessionExecutionKind = Literal[
    "checkpoint",
    "wait",
    "retry_intent",
    "terminal",
    "unexpected",
]

SessionOutcome = Literal["done", "already_satisfied", "blocked", "needs_decision"]
SessionResumeContextBuilder = Callable[[ExecutionSession], str]


@dataclass(frozen=True)
class SessionRuntimeAdapter:
    session_manager: SessionManagerProtocol
    wakeup_dispatcher: WakeupDispatcherProtocol
    max_iterations: int = 8
    resume_context_builder: SessionResumeContextBuilder | None = None
    allow_wait_suspension: bool = False


@dataclass(frozen=True)
class CheckpointPayload:
    phase: str
    summary: str | None = None
    artifacts: dict[str, Any] | None = None
    tool_state: dict[str, Any] | None = None
    subtasks: list[Any] | None = None
    next_action_hint: str | None = None
    next_action_params: dict[str, Any] | None = None


@dataclass(frozen=True)
class WaitPayload:
    wait_type: str
    summary: str | None = None
    resume_hint: str | None = None
    wake_condition: dict[str, Any] | None = None


@dataclass(frozen=True)
class RetryIntentPayload:
    failure_reason: str
    summary: str | None = None
    resume_hint: str | None = None
    retry_prompt_template: str | None = None


@dataclass(frozen=True)
class TerminalOutcomePayload:
    outcome: SessionOutcome
    summary: str | None = None
    decision_required: bool = False
    reason_code: str | None = None
    blocked_reason: str | None = None
    next_action_hint: str | None = None
    failure_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class ParsedExecutorPayload:
    kind: SessionExecutionKind
    checkpoint: CheckpointPayload | None = None
    wait: WaitPayload | None = None
    retry_intent: RetryIntentPayload | None = None
    terminal: TerminalOutcomePayload | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    unexpected_reason: str | None = None


def build_session_runtime_adapter(
    *,
    session_manager: SessionManagerProtocol,
    wakeup_dispatcher: WakeupDispatcherProtocol | None = None,
    max_iterations: int = 8,
    resume_context_builder: SessionResumeContextBuilder | None = None,
    allow_wait_suspension: bool = False,
) -> SessionRuntimeAdapter:
    if wakeup_dispatcher is None:
        from .wakeup_dispatcher import InMemoryWakeupDispatcher

        wakeup_dispatcher = InMemoryWakeupDispatcher()
    return SessionRuntimeAdapter(
        session_manager=session_manager,
        wakeup_dispatcher=wakeup_dispatcher,
        max_iterations=max_iterations,
        resume_context_builder=resume_context_builder,
        allow_wait_suspension=allow_wait_suspension,
    )


def _is_session_runtime_adapter(value: object) -> bool:
    return (
        hasattr(value, "session_manager")
        and hasattr(value, "wakeup_dispatcher")
        and hasattr(value, "max_iterations")
        and hasattr(value, "allow_wait_suspension")
    )


def _looks_like_session_manager(value: object) -> bool:
    required_attributes = (
        "create_session",
        "get_session",
        "update_session_status",
        "suspend_session",
        "resume_session",
        "update_session_phase",
        "append_checkpoint",
        "get_latest_checkpoint",
        "record_policy_resolution",
        "build_resume_context",
        "list_active_sessions_for_work",
    )
    return all(hasattr(value, attribute) for attribute in required_attributes)


def coerce_session_runtime_adapter(
    session_runtime: object | None,
    *,
    max_iterations: int = 8,
) -> SessionRuntimeAdapter | None:
    if session_runtime in (None, False, True):
        return None
    if isinstance(session_runtime, SessionRuntimeAdapter):
        return session_runtime
    if _is_session_runtime_adapter(session_runtime):
        return build_session_runtime_adapter(
            session_manager=session_runtime.session_manager,
            wakeup_dispatcher=session_runtime.wakeup_dispatcher,
            max_iterations=int(
                getattr(session_runtime, "max_iterations", max_iterations) or max_iterations
            ),
            resume_context_builder=getattr(
                session_runtime, "resume_context_builder", None
            ),
            allow_wait_suspension=bool(
                getattr(session_runtime, "allow_wait_suspension", False)
            ),
        )
    if _looks_like_session_manager(session_runtime):
        return build_session_runtime_adapter(
            session_manager=session_runtime,
            max_iterations=max_iterations,
            resume_context_builder=getattr(
                session_runtime, "resume_context_builder", None
            ),
        )
    raise TypeError(
        f"unsupported session runtime: {type(session_runtime).__name__}"
    )


def _as_raw_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_lower_str(value: Any) -> str:
    return _as_str(value).lower()


def _is_valid_terminal_outcome(outcome: str) -> bool:
    return outcome in VALID_SESSION_OUTCOMES


def parse_executor_payload(payload: Any) -> ParsedExecutorPayload:
    raw_payload = _as_raw_payload(payload)
    if not raw_payload:
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_UNEXPECTED,
            raw_payload={},
            unexpected_reason=REASON_CODE_INVALID_EXECUTOR_PAYLOAD,
        )

    execution_kind = _as_lower_str(raw_payload.get("execution_kind"))
    outcome = _as_lower_str(raw_payload.get("outcome"))

    if execution_kind == EXECUTION_KIND_CHECKPOINT:
        phase = _as_str(raw_payload.get("phase"))
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_CHECKPOINT,
            checkpoint=CheckpointPayload(
                phase=phase,
                summary=raw_payload.get("summary"),
                artifacts=raw_payload.get("artifacts"),
                tool_state=raw_payload.get("tool_state"),
                subtasks=raw_payload.get("subtasks"),
                next_action_hint=raw_payload.get("next_action_hint"),
                next_action_params=raw_payload.get("next_action_params"),
            ),
            raw_payload=raw_payload,
        )

    if execution_kind == EXECUTION_KIND_WAIT:
        wait_type = _as_str(raw_payload.get("wait_type"))
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_WAIT,
            wait=WaitPayload(
                wait_type=wait_type,
                summary=raw_payload.get("summary"),
                resume_hint=raw_payload.get("resume_hint"),
                wake_condition=raw_payload,
            ),
            raw_payload=raw_payload,
        )

    if execution_kind == EXECUTION_KIND_RETRY_INTENT:
        failure_reason = _as_str(raw_payload.get("failure_reason"))
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_RETRY_INTENT,
            retry_intent=RetryIntentPayload(
                failure_reason=failure_reason,
                summary=raw_payload.get("summary"),
                resume_hint=raw_payload.get("resume_hint"),
                retry_prompt_template=raw_payload.get("retry_prompt_template"),
            ),
            raw_payload=raw_payload,
        )

    if _is_valid_terminal_outcome(outcome):
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_TERMINAL,
            terminal=TerminalOutcomePayload(
                outcome=outcome,  # type: ignore[arg-type]
                summary=raw_payload.get("summary"),
                decision_required=bool(raw_payload.get("decision_required", False)),
                reason_code=raw_payload.get("reason_code"),
                blocked_reason=raw_payload.get("blocked_reason"),
                next_action_hint=raw_payload.get("next_action_hint"),
                failure_context=raw_payload,
            ),
            raw_payload=raw_payload,
        )

    if execution_kind == EXECUTION_KIND_TERMINAL:
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_UNEXPECTED,
            raw_payload=raw_payload,
            unexpected_reason=REASON_CODE_MISSING_SESSION_OUTCOME,
        )

    if not execution_kind:
        return ParsedExecutorPayload(
            kind=EXECUTION_KIND_UNEXPECTED,
            raw_payload=raw_payload,
            unexpected_reason=REASON_CODE_MISSING_EXECUTION_KIND,
        )

    return ParsedExecutorPayload(
        kind=EXECUTION_KIND_UNEXPECTED,
        raw_payload=raw_payload,
        unexpected_reason=REASON_CODE_UNEXPECTED_SESSION_PAYLOAD,
    )
