from __future__ import annotations

from ..execution_protocol import classify_execution_payload

NON_TERMINAL_REASON_CODES = {
    "awaiting_background_context",
    "awaiting_background_research",
    "waiting_for_context_gathering",
    "research_in_progress",
    "context_gathering_in_progress",
}

PAUSED_REASON_CODES = {
    "awaiting_user_input",
    "ask_next_step",
    "awaiting_next_step",
    "paused_for_input",
}

__all__ = [
    "NON_TERMINAL_REASON_CODES",
    "PAUSED_REASON_CODES",
    "classify_execution_payload",
]
