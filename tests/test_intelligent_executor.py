from __future__ import annotations

import json

from stardrifter_orchestration_mvp.intelligent_executor import (
    IntelligentExecutor,
    IntelligentExecutorConfig,
    IntelligentVerifierConfig,
    LLMRequestError,
    LLMVerifier,
    ModelTurn,
    ToolInvocation,
    WorkspaceToolbox,
    llm_executor_enabled,
    llm_verifier_enabled,
)
from stardrifter_orchestration_mvp.models import WorkItem


class _FakeClient:
    def __init__(self, turns: list[ModelTurn] | None = None, raise_first: bool = False):
        self.turns = turns or []
        self.raise_first = raise_first
        self.calls = 0

    def complete_with_tools(self, **kwargs) -> ModelTurn:
        del kwargs
        self.calls += 1
        if self.raise_first and self.calls == 1:
            raise LLMRequestError("transient", reason_code="upstream_api_error", retryable=True)
        if not self.turns:
            raise AssertionError("no fake turns configured")
        return self.turns.pop(0)

    def complete_text(self, **kwargs) -> str:
        del kwargs
        return '{"passed": true, "summary": "ok"}'


def _make_work_item() -> WorkItem:
    return WorkItem(
        id="task-llm-1",
        title="[09-IMPL] intelligent executor",
        lane="Lane 09",
        wave="wave-1",
        status="in_progress",
        task_type="core_path",
    )


def test_llm_executor_enabled_by_env_and_virtual_command(monkeypatch):
    monkeypatch.delenv("STARDRIFTER_ENABLE_LLM_EXECUTOR", raising=False)
    assert llm_executor_enabled(command_template="echo hi") is False
    assert llm_executor_enabled(command_template="llm://executor") is True
    monkeypatch.setenv("STARDRIFTER_ENABLE_LLM_EXECUTOR", "1")
    assert llm_executor_enabled(command_template="echo hi") is True


def test_llm_verifier_enabled_by_env_and_virtual_command(monkeypatch):
    monkeypatch.delenv("STARDRIFTER_ENABLE_LLM_VERIFIER", raising=False)
    assert llm_verifier_enabled(command_template="pytest -q") is False
    assert llm_verifier_enabled(command_template="llm://verifier") is True
    monkeypatch.setenv("STARDRIFTER_ENABLE_LLM_VERIFIER", "true")
    assert llm_verifier_enabled(command_template="pytest -q") is True


def test_intelligent_executor_handles_tool_then_terminal_payload(tmp_path):
    source = tmp_path / "hello.txt"
    source.write_text("hello executor")
    client = _FakeClient(
        turns=[
            ModelTurn(
                text="",
                tool_calls=(
                    ToolInvocation(
                        call_id="call-1",
                        name="read_file",
                        arguments={"path": "hello.txt"},
                    ),
                ),
                assistant_message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"hello.txt"}'},
                        }
                    ],
                },
            ),
            ModelTurn(
                text='{"outcome":"done","summary":"implemented"}',
                tool_calls=(),
                assistant_message={"role": "assistant", "content": '{"outcome":"done","summary":"implemented"}'},
            ),
        ]
    )
    executor = IntelligentExecutor(
        repo_root=tmp_path,
        config=IntelligentExecutorConfig(
            provider="openai",
            model="gpt-test",
            max_turns=6,
            max_output_tokens=256,
            timeout_seconds=30,
            max_retries=0,
            retry_backoff_seconds=0.01,
            context_chars=2000,
            context_window_chars=3000,
            keep_recent_messages=4,
            tool_loop_hard_limit=3,
        ),
        fallback_command_template="echo shell",
        model_client=client,
    )

    result = executor(_make_work_item(), workspace_path=tmp_path)

    assert result.success is True
    assert result.result_payload_json is not None
    assert result.result_payload_json["outcome"] == "done"
    assert "read_file" in result.stdout_digest


def test_intelligent_executor_detects_repeated_tool_loop(tmp_path):
    loop_turn = ModelTurn(
        text="",
        tool_calls=(
            ToolInvocation(
                call_id="call-1",
                name="list_files",
                arguments={"path": "."},
            ),
        ),
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "list_files", "arguments": '{"path":"."}'},
                }
            ],
        },
    )
    client = _FakeClient(turns=[loop_turn, loop_turn, loop_turn])
    executor = IntelligentExecutor(
        repo_root=tmp_path,
        config=IntelligentExecutorConfig(
            provider="openai",
            model="gpt-test",
            max_turns=5,
            max_output_tokens=256,
            timeout_seconds=30,
            max_retries=0,
            retry_backoff_seconds=0.01,
            context_chars=1000,
            context_window_chars=3000,
            keep_recent_messages=3,
            tool_loop_hard_limit=2,
        ),
        fallback_command_template="echo shell",
        model_client=client,
    )

    result = executor(_make_work_item(), workspace_path=tmp_path)

    assert result.success is False
    assert result.blocked_reason == "tool_loop_detected"


def test_intelligent_executor_retries_retryable_llm_request_error(tmp_path):
    client = _FakeClient(
        turns=[
            ModelTurn(
                text='{"outcome":"done","summary":"after retry"}',
                tool_calls=(),
                assistant_message={"role": "assistant", "content": '{"outcome":"done","summary":"after retry"}'},
            )
        ],
        raise_first=True,
    )
    executor = IntelligentExecutor(
        repo_root=tmp_path,
        config=IntelligentExecutorConfig(
            provider="openai",
            model="gpt-test",
            max_turns=2,
            max_output_tokens=256,
            timeout_seconds=30,
            max_retries=1,
            retry_backoff_seconds=0.001,
            context_chars=1000,
            context_window_chars=3000,
            keep_recent_messages=3,
            tool_loop_hard_limit=3,
        ),
        fallback_command_template="echo shell",
        model_client=client,
    )

    result = executor(_make_work_item(), workspace_path=tmp_path)

    assert client.calls == 2
    assert result.success is True
    assert result.result_payload_json["outcome"] == "done"


def test_workspace_bash_tool_blocks_unsafe_command(monkeypatch, tmp_path):
    monkeypatch.delenv("STARDRIFTER_LLM_BASH_ALLOW_UNSAFE", raising=False)
    toolbox = WorkspaceToolbox(workspace_path=tmp_path)

    output = toolbox.run(
        ToolInvocation(
            call_id="c1",
            name="bash",
            arguments={"command": "rm -rf /tmp/data"},
        )
    )
    payload = json.loads(output)

    assert payload["ok"] is False
    assert payload["reason_code"] == "security_concern"


def test_workspace_bash_tool_allows_unsafe_when_override_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("STARDRIFTER_LLM_BASH_ALLOW_UNSAFE", "1")
    toolbox = WorkspaceToolbox(workspace_path=tmp_path)

    output = toolbox.run(
        ToolInvocation(
            call_id="c2",
            name="bash",
            arguments={"command": 'python3 -c "print(123)"'},
        )
    )
    payload = json.loads(output)

    assert payload["ok"] is True
    assert payload["returncode"] == 0


def test_llm_verifier_combines_test_and_llm_assessment(tmp_path):
    class _VerifierClient:
        def complete_with_tools(self, **kwargs):  # pragma: no cover
            raise AssertionError("not used")

        def complete_text(self, **kwargs) -> str:
            del kwargs
            return '{"passed": true, "summary": "looks good"}'

    verifier = LLMVerifier(
        repo_root=tmp_path,
        command_template='python3 -c "print(1)"',
        check_type="pytest",
        config=IntelligentVerifierConfig(
            provider="openai",
            model="gpt-test",
            timeout_seconds=30,
            max_output_tokens=256,
            context_chars=2000,
            diff_chars=1000,
        ),
        model_client=_VerifierClient(),
    )

    evidence = verifier(_make_work_item(), workspace_path=tmp_path)

    assert evidence.passed is True
    assert evidence.check_type == "pytest+llm"
    assert evidence.exit_code == 0


def test_llm_verifier_fails_when_tests_fail_even_if_llm_passes(tmp_path):
    class _VerifierClient:
        def complete_with_tools(self, **kwargs):  # pragma: no cover
            raise AssertionError("not used")

        def complete_text(self, **kwargs) -> str:
            del kwargs
            return '{"passed": true, "summary": "looks good"}'

    verifier = LLMVerifier(
        repo_root=tmp_path,
        command_template='python3 -c "import sys; sys.exit(2)"',
        check_type="pytest",
        config=IntelligentVerifierConfig(
            provider="openai",
            model="gpt-test",
            timeout_seconds=30,
            max_output_tokens=256,
            context_chars=2000,
            diff_chars=1000,
        ),
        model_client=_VerifierClient(),
    )

    evidence = verifier(_make_work_item(), workspace_path=tmp_path)

    assert evidence.passed is False
    assert evidence.exit_code == 2
