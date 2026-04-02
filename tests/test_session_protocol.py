from __future__ import annotations

from taskplane.session_protocol import (
    CheckpointPayload,
    EXECUTION_KIND_CHECKPOINT,
    EXECUTION_KIND_TERMINAL,
    EXECUTION_KIND_WAIT,
    ParsedExecutorPayload,
    RetryIntentPayload,
    SESSION_OUTCOME_DONE,
    SESSION_OUTCOME_NEEDS_DECISION,
    REASON_CODE_MISSING_EXECUTION_KIND,
    TerminalOutcomePayload,
    WaitPayload,
    parse_executor_payload,
)


class TestParseExecutorPayload:
    def test_parses_checkpoint_payload(self) -> None:
        parsed = parse_executor_payload(
            {
                "execution_kind": EXECUTION_KIND_CHECKPOINT,
                "phase": "researching",
                "summary": "Found 3 modules",
                "artifacts": {"files": ["a.py"]},
                "tool_state": {"cursor": "abc"},
                "subtasks": ["scan", "summarize"],
                "next_action_hint": "continue",
            }
        )

        assert parsed == ParsedExecutorPayload(
            kind=EXECUTION_KIND_CHECKPOINT,
            checkpoint=CheckpointPayload(
                phase="researching",
                summary="Found 3 modules",
                artifacts={"files": ["a.py"]},
                tool_state={"cursor": "abc"},
                subtasks=["scan", "summarize"],
                next_action_hint="continue",
                next_action_params=None,
            ),
            wait=None,
            retry_intent=None,
            terminal=None,
            raw_payload={
                "execution_kind": EXECUTION_KIND_CHECKPOINT,
                "phase": "researching",
                "summary": "Found 3 modules",
                "artifacts": {"files": ["a.py"]},
                "tool_state": {"cursor": "abc"},
                "subtasks": ["scan", "summarize"],
                "next_action_hint": "continue",
            },
            unexpected_reason=None,
        )

    def test_parses_terminal_outcome_from_legacy_fallback(self) -> None:
        parsed = parse_executor_payload(
            {
                "outcome": SESSION_OUTCOME_DONE,
                "summary": "task completed",
            }
        )

        assert parsed.kind == EXECUTION_KIND_TERMINAL
        assert parsed.terminal == TerminalOutcomePayload(
            outcome=SESSION_OUTCOME_DONE,
            summary="task completed",
            decision_required=False,
            reason_code=None,
            blocked_reason=None,
            next_action_hint=None,
            failure_context={
                "outcome": SESSION_OUTCOME_DONE,
                "summary": "task completed",
            },
        )

    def test_parses_retry_intent_payload(self) -> None:
        parsed = parse_executor_payload(
            {
                "execution_kind": "retry_intent",
                "failure_reason": "timeout",
                "summary": "executor timed out",
                "retry_prompt_template": "Retry with narrower scope",
            }
        )

        assert parsed.retry_intent == RetryIntentPayload(
            failure_reason="timeout",
            summary="executor timed out",
            resume_hint=None,
            retry_prompt_template="Retry with narrower scope",
        )

    def test_parses_wait_payload(self) -> None:
        parsed = parse_executor_payload(
            {
                "execution_kind": EXECUTION_KIND_WAIT,
                "wait_type": "subagent_result",
                "summary": "Waiting for subagent",
                "resume_hint": "Resume at synthesis",
            }
        )

        assert parsed.wait == WaitPayload(
            wait_type="subagent_result",
            summary="Waiting for subagent",
            resume_hint="Resume at synthesis",
            wake_condition={
                "execution_kind": EXECUTION_KIND_WAIT,
                "wait_type": "subagent_result",
                "summary": "Waiting for subagent",
                "resume_hint": "Resume at synthesis",
            },
        )

    def test_marks_unknown_payload_as_unexpected(self) -> None:
        parsed = parse_executor_payload({"summary": "mystery"})

        assert parsed.kind == "unexpected"
        assert parsed.unexpected_reason == REASON_CODE_MISSING_EXECUTION_KIND
        assert parsed.raw_payload == {"summary": "mystery"}
