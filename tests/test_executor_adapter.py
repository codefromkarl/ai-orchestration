from __future__ import annotations

from taskplane.executor_adapter import (
    parse_executor_output,
)


class TestParseExecutorOutput:
    def test_marker_result(self) -> None:
        stdout = (
            'TASKPLANE_EXECUTION_RESULT_JSON={"outcome":"done","summary":"completed"}'
        )
        result = parse_executor_output(stdout, "", 0)
        assert result.success is True
        assert result.payload["outcome"] == "done"

    def test_marker_checkpoint(self) -> None:
        stdout = 'TASKPLANE_EXECUTION_CHECKPOINT_JSON={"execution_kind":"checkpoint","phase":"researching","summary":"found modules"}'
        result = parse_executor_output(stdout, "", 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "checkpoint"

    def test_marker_wait(self) -> None:
        stdout = 'TASKPLANE_EXECUTION_WAIT_JSON={"execution_kind":"wait","wait_type":"timer","summary":"waiting"}'
        result = parse_executor_output(stdout, "", 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "wait"

    def test_text_event_extraction(self) -> None:
        import json as _json

        payload_json = '{"outcome":"blocked","summary":"no changes"}'
        escaped = _json.dumps(payload_json)
        stdout = f'{{"type":"text","part":{{"text":{escaped}}}}}'
        result = parse_executor_output(stdout, "", 0)
        assert result.success is True
        assert result.payload["outcome"] == "blocked"

    def test_nonzero_exit(self) -> None:
        result = parse_executor_output("", "", 1)
        assert result.success is False
        assert result.payload["reason_code"] == "opencode-exit-nonzero"

    def test_timeout_exit(self) -> None:
        result = parse_executor_output("", "", 124)
        assert result.success is False
        assert result.payload["reason_code"] == "timeout"

    def test_empty_output_zero_exit(self) -> None:
        result = parse_executor_output("", "", 0)
        assert result.success is False
        assert result.payload == {}

    def test_marker_takes_precedence_over_text_events(self) -> None:
        marker = 'TASKPLANE_EXECUTION_RESULT_JSON={"outcome":"done","summary":"from marker"}'
        text_event = '{"type":"text","part":{"text":"{\\"outcome\\":\\"blocked\\",\\"summary\\":\\"from text\\"}"}}'
        result = parse_executor_output(f"{text_event}\n{marker}", "", 0)
        assert result.payload["summary"] == "from marker"

    def test_stderr_marker_parsed(self) -> None:
        stderr = 'TASKPLANE_EXECUTION_CHECKPOINT_JSON={"execution_kind":"checkpoint","phase":"verifying","summary":"tests running"}'
        result = parse_executor_output("", stderr, 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "checkpoint"

    def test_text_event_checkpoint(self) -> None:
        import json as _json

        payload_json = '{"execution_kind":"checkpoint","phase":"researching","summary":"exploring"}'
        escaped = _json.dumps(payload_json)
        stdout = f'{{"type":"text","part":{{"text":{escaped}}}}}'
        result = parse_executor_output(stdout, "", 0)
        assert result.success is True
        assert result.payload["execution_kind"] == "checkpoint"
