from __future__ import annotations

import json

# -----------------------------------------------------------------------
# Existing terminal result marker
# -----------------------------------------------------------------------
EXECUTION_RESULT_MARKER = "TASKPLANE_EXECUTION_RESULT_JSON="

# -----------------------------------------------------------------------
# Intermediate execution markers (Phase A)
# -----------------------------------------------------------------------
EXECUTION_CHECKPOINT_MARKER = "TASKPLANE_EXECUTION_CHECKPOINT_JSON="
EXECUTION_WAIT_MARKER = "TASKPLANE_EXECUTION_WAIT_JSON="
EXECUTION_RETRY_INTENT_MARKER = "TASKPLANE_EXECUTION_RETRY_INTENT_JSON="

# -----------------------------------------------------------------------
# Valid value sets
# -----------------------------------------------------------------------
VALID_EXECUTION_KINDS: set[str] = {
    "terminal",
    "checkpoint",
    "wait",
    "retry_intent",
    "handoff",
}

VALID_WAIT_TYPES: set[str] = {
    "timer",
    "subagent_result",
    "tool_result",
    "external_event",
    "policy_resolved",
    "manual_unblock",
}

VALID_CHECKPOINT_PHASES: set[str] = {
    "planning",
    "researching",
    "implementing",
    "verifying",
    "repairing",
    "integrating",
}


# -----------------------------------------------------------------------
# Validation functions
# -----------------------------------------------------------------------


def validate_checkpoint_payload(payload: dict) -> list[str]:
    """Validate a checkpoint execution payload. Returns list of errors."""
    errors: list[str] = []
    if payload.get("execution_kind") != "checkpoint":
        errors.append("execution_kind must be 'checkpoint'")
    phase = payload.get("phase")
    if not phase:
        errors.append("'phase' is required for checkpoint")
    elif phase not in VALID_CHECKPOINT_PHASES:
        errors.append(
            f"Invalid phase: {phase}. Must be one of {sorted(VALID_CHECKPOINT_PHASES)}"
        )
    if not payload.get("summary"):
        errors.append("'summary' is required for checkpoint")
    return errors


def validate_wait_payload(payload: dict) -> list[str]:
    """Validate a wait execution payload. Returns list of errors."""
    errors: list[str] = []
    if payload.get("execution_kind") != "wait":
        errors.append("execution_kind must be 'wait'")
    wait_type = payload.get("wait_type")
    if not wait_type:
        errors.append("'wait_type' is required for wait payload")
    elif wait_type not in VALID_WAIT_TYPES:
        errors.append(
            f"Invalid wait_type: {wait_type}. Must be one of {sorted(VALID_WAIT_TYPES)}"
        )
    if not payload.get("summary"):
        errors.append("'summary' is required for wait payload")
    return errors


def validate_retry_intent_payload(payload: dict) -> list[str]:
    """Validate a retry_intent execution payload. Returns list of errors."""
    errors: list[str] = []
    if payload.get("execution_kind") != "retry_intent":
        errors.append("execution_kind must be 'retry_intent'")
    if not payload.get("failure_reason"):
        errors.append("'failure_reason' is required for retry_intent")
    if not payload.get("summary"):
        errors.append("'summary' is required for retry_intent")
    return errors


def classify_execution_payload(payload: dict) -> str:
    """Classify an execution payload by its execution_kind."""
    kind = str(payload.get("execution_kind") or "").strip().lower()
    if kind in VALID_EXECUTION_KINDS:
        return kind
    # Legacy fallback: if no execution_kind but has outcome, treat as terminal
    if payload.get("outcome"):
        return "terminal"
    return "unknown"


# -----------------------------------------------------------------------
# Marker formatting helpers
# -----------------------------------------------------------------------


def format_checkpoint_marker(payload: dict) -> str:
    """Format a checkpoint payload with its marker prefix."""
    return EXECUTION_CHECKPOINT_MARKER + json.dumps(payload, ensure_ascii=False)


def format_wait_marker(payload: dict) -> str:
    """Format a wait payload with its marker prefix."""
    return EXECUTION_WAIT_MARKER + json.dumps(payload, ensure_ascii=False)


def format_retry_intent_marker(payload: dict) -> str:
    """Format a retry_intent payload with its marker prefix."""
    return EXECUTION_RETRY_INTENT_MARKER + json.dumps(payload, ensure_ascii=False)
