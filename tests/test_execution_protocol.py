from __future__ import annotations

import json

from stardrifter_orchestration_mvp.execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_RETRY_INTENT_MARKER,
    EXECUTION_WAIT_MARKER,
    VALID_CHECKPOINT_PHASES,
    VALID_EXECUTION_KINDS,
    VALID_WAIT_TYPES,
    classify_execution_payload,
    format_checkpoint_marker,
    format_retry_intent_marker,
    format_wait_marker,
    validate_checkpoint_payload,
    validate_retry_intent_payload,
    validate_wait_payload,
)


class TestValidateCheckpointPayload:
    def test_valid_checkpoint(self) -> None:
        payload = {
            "execution_kind": "checkpoint",
            "phase": "researching",
            "summary": "Found 3 candidate modules",
        }
        assert validate_checkpoint_payload(payload) == []

    def test_missing_execution_kind(self) -> None:
        payload = {"phase": "researching", "summary": "test"}
        errors = validate_checkpoint_payload(payload)
        assert any("execution_kind" in e for e in errors)

    def test_missing_phase(self) -> None:
        payload = {"execution_kind": "checkpoint", "summary": "test"}
        errors = validate_checkpoint_payload(payload)
        assert any("'phase' is required" in e for e in errors)

    def test_invalid_phase(self) -> None:
        payload = {
            "execution_kind": "checkpoint",
            "phase": "invalid_phase",
            "summary": "test",
        }
        errors = validate_checkpoint_payload(payload)
        assert any("Invalid phase" in e for e in errors)

    def test_missing_summary(self) -> None:
        payload = {"execution_kind": "checkpoint", "phase": "researching"}
        errors = validate_checkpoint_payload(payload)
        assert any("'summary' is required" in e for e in errors)

    def test_all_valid_phases(self) -> None:
        for phase in VALID_CHECKPOINT_PHASES:
            payload = {
                "execution_kind": "checkpoint",
                "phase": phase,
                "summary": f"phase {phase}",
            }
            assert validate_checkpoint_payload(payload) == [], f"phase {phase} failed"


class TestValidateWaitPayload:
    def test_valid_wait(self) -> None:
        payload = {
            "execution_kind": "wait",
            "wait_type": "subagent_result",
            "summary": "Waiting for implementation subagent",
        }
        assert validate_wait_payload(payload) == []

    def test_missing_wait_type(self) -> None:
        payload = {"execution_kind": "wait", "summary": "test"}
        errors = validate_wait_payload(payload)
        assert any("'wait_type' is required" in e for e in errors)

    def test_invalid_wait_type(self) -> None:
        payload = {
            "execution_kind": "wait",
            "wait_type": "invalid_type",
            "summary": "test",
        }
        errors = validate_wait_payload(payload)
        assert any("Invalid wait_type" in e for e in errors)

    def test_all_valid_wait_types(self) -> None:
        for wt in VALID_WAIT_TYPES:
            payload = {
                "execution_kind": "wait",
                "wait_type": wt,
                "summary": f"wait {wt}",
            }
            assert validate_wait_payload(payload) == [], f"wait_type {wt} failed"


class TestValidateRetryIntentPayload:
    def test_valid_retry_intent(self) -> None:
        payload = {
            "execution_kind": "retry_intent",
            "failure_reason": "timeout",
            "summary": "Executor timed out, retrying",
        }
        assert validate_retry_intent_payload(payload) == []

    def test_missing_failure_reason(self) -> None:
        payload = {"execution_kind": "retry_intent", "summary": "test"}
        errors = validate_retry_intent_payload(payload)
        assert any("'failure_reason' is required" in e for e in errors)

    def test_missing_summary(self) -> None:
        payload = {
            "execution_kind": "retry_intent",
            "failure_reason": "timeout",
        }
        errors = validate_retry_intent_payload(payload)
        assert any("'summary' is required" in e for e in errors)


class TestClassifyExecutionPayload:
    def test_checkpoint(self) -> None:
        payload = {
            "execution_kind": "checkpoint",
            "phase": "researching",
            "summary": "x",
        }
        assert classify_execution_payload(payload) == "checkpoint"

    def test_wait(self) -> None:
        payload = {"execution_kind": "wait", "wait_type": "timer", "summary": "x"}
        assert classify_execution_payload(payload) == "wait"

    def test_retry_intent(self) -> None:
        payload = {
            "execution_kind": "retry_intent",
            "failure_reason": "x",
            "summary": "x",
        }
        assert classify_execution_payload(payload) == "retry_intent"

    def test_terminal(self) -> None:
        payload = {"execution_kind": "terminal", "outcome": "done"}
        assert classify_execution_payload(payload) == "terminal"

    def test_legacy_terminal(self) -> None:
        payload = {"outcome": "done", "summary": "completed"}
        assert classify_execution_payload(payload) == "terminal"

    def test_unknown(self) -> None:
        payload = {"something": "else"}
        assert classify_execution_payload(payload) == "unknown"


class TestFormatMarkers:
    def test_format_checkpoint_marker(self) -> None:
        payload = {
            "execution_kind": "checkpoint",
            "phase": "researching",
            "summary": "x",
        }
        result = format_checkpoint_marker(payload)
        assert result.startswith(EXECUTION_CHECKPOINT_MARKER)
        parsed = json.loads(result[len(EXECUTION_CHECKPOINT_MARKER) :])
        assert parsed["execution_kind"] == "checkpoint"

    def test_format_wait_marker(self) -> None:
        payload = {"execution_kind": "wait", "wait_type": "timer", "summary": "x"}
        result = format_wait_marker(payload)
        assert result.startswith(EXECUTION_WAIT_MARKER)
        parsed = json.loads(result[len(EXECUTION_WAIT_MARKER) :])
        assert parsed["execution_kind"] == "wait"

    def test_format_retry_intent_marker(self) -> None:
        payload = {
            "execution_kind": "retry_intent",
            "failure_reason": "x",
            "summary": "x",
        }
        result = format_retry_intent_marker(payload)
        assert result.startswith(EXECUTION_RETRY_INTENT_MARKER)
        parsed = json.loads(result[len(EXECUTION_RETRY_INTENT_MARKER) :])
        assert parsed["execution_kind"] == "retry_intent"


class TestConstants:
    def test_execution_result_marker_unchanged(self) -> None:
        assert EXECUTION_RESULT_MARKER == "STARDRIFTER_EXECUTION_RESULT_JSON="

    def test_valid_execution_kinds(self) -> None:
        assert "terminal" in VALID_EXECUTION_KINDS
        assert "checkpoint" in VALID_EXECUTION_KINDS
        assert "wait" in VALID_EXECUTION_KINDS
        assert "retry_intent" in VALID_EXECUTION_KINDS
        assert "handoff" in VALID_EXECUTION_KINDS
