from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
