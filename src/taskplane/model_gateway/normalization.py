from __future__ import annotations

from typing import Any

from .execution_compat import (
    NON_TERMINAL_REASON_CODES,
    PAUSED_REASON_CODES,
    classify_execution_payload,
)


def build_timeout_payload(
    *,
    timeout_seconds: int,
    hard_cap_seconds: int | None = None,
    timeout_kind: str | None = None,
    partial_output: str = "",
    tool_name: str = "opencode",
    resume_context_builder: Any = None,
) -> dict[str, Any]:
    if timeout_kind == "hard_cap" and hard_cap_seconds is not None:
        summary = f"{tool_name} exceeded hard cap after {hard_cap_seconds} seconds"
    else:
        summary = f"{tool_name} exceeded timeout after {timeout_seconds} seconds"
    if partial_output:
        summary = f"{summary}; partial output: {partial_output}"
    payload: dict[str, Any] = {
        "outcome": "blocked",
        "reason_code": "timeout",
        "summary": summary,
        "decision_required": False,
    }
    if resume_context_builder is not None:
        resume_context = resume_context_builder(partial_output)
        if resume_context:
            payload["resume_context"] = resume_context
    return payload


def is_non_terminal_payload(payload: dict[str, Any]) -> bool:
    kind = classify_execution_payload(payload)
    if kind in {"checkpoint", "wait", "retry_intent"}:
        return False
    reason_code = str(payload.get("reason_code") or "").strip().lower()
    summary = str(payload.get("summary") or "").strip().lower()
    if reason_code in NON_TERMINAL_REASON_CODES:
        return True
    disallowed_summary_markers = (
        "background context",
        "background research",
        "context gathering",
        "still in flight",
        "awaiting background",
        "waiting for context",
    )
    return any(marker in summary for marker in disallowed_summary_markers)


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reason_code = str(payload.get("reason_code") or "").strip().lower()
    if reason_code in PAUSED_REASON_CODES:
        return {
            **payload,
            "outcome": "needs_decision",
            "decision_required": True,
        }
    return payload


def classify_nonzero_exit_payload(
    *, returncode: int, tool_name: str = "opencode"
) -> dict[str, Any]:
    if returncode in {130, 143}:
        return {
            "outcome": "blocked",
            "reason_code": "interrupted_retryable",
            "summary": f"{tool_name} was interrupted before reaching a terminal result",
            "decision_required": False,
        }
    return {
        "outcome": "blocked",
        "reason_code": "tooling_error",
        "summary": f"{tool_name} exited with code {returncode}",
        "decision_required": False,
    }
