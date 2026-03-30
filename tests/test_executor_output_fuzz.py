from __future__ import annotations

import json
from stardrifter_orchestration_mvp.executor_adapter import parse_executor_output
from stardrifter_orchestration_mvp.execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_WAIT_MARKER,
)


class TestExecutorOutputFuzz:
    def test_empty_strings(self) -> None:
        result = parse_executor_output("", "", 0)
        assert result.success is False
        assert result.payload == {}

    def test_only_whitespace(self) -> None:
        result = parse_executor_output("   \n\n  \t  ", "  \n  ", 0)
        assert result.success is False

    def test_binary_garbage(self) -> None:
        raw = "\x00\x01\x02\xff\xfe"
        result = parse_executor_output(raw, "", 0)
        assert result.success is False

    def test_very_long_output(self) -> None:
        noise = "x" * 100000
        marker = f"{EXECUTION_RESULT_MARKER}{json.dumps({'outcome': 'done', 'summary': 'ok'})}"
        result = parse_executor_output(f"{noise}\n{marker}\n{noise}", "", 0)
        assert result.success is True
        assert result.payload["outcome"] == "done"

    def test_multiple_markers_last_one_wins(self) -> None:
        m1 = f"{EXECUTION_RESULT_MARKER}{json.dumps({'outcome': 'blocked', 'summary': 'first'})}"
        m2 = f"{EXECUTION_CHECKPOINT_MARKER}{json.dumps({'execution_kind': 'checkpoint', 'phase': 'researching', 'summary': 'second'})}"
        m3 = f"{EXECUTION_RESULT_MARKER}{json.dumps({'outcome': 'done', 'summary': 'third'})}"
        result = parse_executor_output(f"{m1}\n{m2}\n{m3}", "", 0)
        assert result.payload["summary"] == "third"

    def test_marker_with_invalid_json(self) -> None:
        result = parse_executor_output(f"{EXECUTION_RESULT_MARKER}not-json", "", 0)
        assert result.success is False

    def test_marker_with_non_dict_json(self) -> None:
        result = parse_executor_output(f"{EXECUTION_RESULT_MARKER}[1,2,3]", "", 0)
        assert result.success is False

    def test_marker_in_stderr(self) -> None:
        stderr = f"{EXECUTION_WAIT_MARKER}{json.dumps({'execution_kind': 'wait', 'wait_type': 'timer', 'summary': 'waiting'})}"
        result = parse_executor_output("", stderr, 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "wait"

    def test_mixed_marker_and_text_events(self) -> None:
        text_event = json.dumps(
            {
                "type": "text",
                "part": {
                    "text": json.dumps({"outcome": "blocked", "summary": "from text"})
                },
            }
        )
        marker = f"{EXECUTION_RESULT_MARKER}{json.dumps({'outcome': 'done', 'summary': 'from marker'})}"
        result = parse_executor_output(f"{text_event}\n{marker}", "", 0)
        assert result.payload["summary"] == "from marker"

    def test_text_event_with_nested_json(self) -> None:
        inner = json.dumps({"outcome": "done", "summary": "nested"})
        outer = json.dumps({"type": "text", "part": {"text": inner}})
        result = parse_executor_output(outer, "", 0)
        assert result.success is True
        assert result.payload["summary"] == "nested"

    def test_text_event_with_non_text_type(self) -> None:
        event = json.dumps({"type": "tool_use", "part": {"text": '{"outcome":"done"}'}})
        result = parse_executor_output(event, "", 0)
        assert result.success is False

    def test_text_event_with_no_part(self) -> None:
        event = json.dumps({"type": "text"})
        result = parse_executor_output(event, "", 0)
        assert result.success is False

    def test_text_event_with_non_dict_part(self) -> None:
        event = json.dumps({"type": "text", "part": "not-a-dict"})
        result = parse_executor_output(event, "", 0)
        assert result.success is False

    def test_text_event_with_empty_text(self) -> None:
        event = json.dumps({"type": "text", "part": {"text": ""}})
        result = parse_executor_output(event, "", 0)
        assert result.success is False

    def test_text_event_with_invalid_inner_json(self) -> None:
        event = json.dumps({"type": "text", "part": {"text": "not-json"}})
        result = parse_executor_output(event, "", 0)
        assert result.success is False

    def test_text_event_checkpoint_payload(self) -> None:
        inner = json.dumps(
            {
                "execution_kind": "checkpoint",
                "phase": "researching",
                "summary": "exploring",
            }
        )
        outer = json.dumps({"type": "text", "part": {"text": inner}})
        result = parse_executor_output(outer, "", 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "checkpoint"

    def test_nonzero_exit_code(self) -> None:
        result = parse_executor_output("", "", 1)
        assert result.success is False
        assert result.exit_code == 1
        assert result.payload["reason_code"] == "opencode-exit-nonzero"

    def test_timeout_exit_code(self) -> None:
        result = parse_executor_output("", "", 124)
        assert result.success is False
        assert result.exit_code == 124
        assert result.payload["reason_code"] == "timeout"

    def test_zero_exit_no_valid_payload(self) -> None:
        result = parse_executor_output("some random output", "", 0)
        assert result.success is False
        assert result.exit_code == 0
        assert result.payload == {}
