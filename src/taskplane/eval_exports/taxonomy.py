from __future__ import annotations

EXECUTION_OUTCOME_VALUES: tuple[str, ...] = (
    "done",
    "blocked",
    "needs_decision",
    "already_satisfied",
)

EXECUTION_REASON_CODE_VALUES: tuple[str, ...] = (
    "timeout",
    "protocol_error",
    "invalid-result-payload",
    "missing-terminal-payload",
    "multiple-terminal-payloads",
    "non_terminal_result_payload",
    "interrupted_retryable",
    "tooling_error",
    "upstream_api_error",
)

VERIFICATION_CLASSIFICATION_VALUES: tuple[str, ...] = (
    "passed",
    "failed",
    "retryable_failure",
    "awaiting_approval",
)

DEFAULT_SCHEMA_VERSION = "v1"
