from __future__ import annotations

import json
import subprocess
import sys

from stardrifter_orchestration_mvp.opencode_task_executor import (
    _build_timeout_payload,
    _build_resume_context_from_output,
    _build_salvaged_done_payload,
    _classify_multiple_terminal_payload,
    _classify_malformed_stream_payload,
    _classify_missing_terminal_payload,
    _classify_upstream_api_error_payload,
    _build_prompt,
    _build_opencode_run_command,
    _load_timeout_seconds,
    _capture_worktree_snapshot,
    _compute_changed_paths,
    _extract_progress_signal_kind,
    _extract_wait_hint,
    _is_bounded_mode_enabled,
    _select_opencode_focus_dir,
    _extract_result_payload,
    _extract_result_payload_details,
    _classify_nonzero_exit_payload,
    _normalize_payload,
    _is_non_terminal_payload,
    _load_hard_cap_seconds,
    _run_monitored_subprocess,
)
from stardrifter_orchestration_mvp.contextweaver_indexing import (
    RepositoryIdentity,
    ensure_contextweaver_index_for_checkout,
)


def test_compute_changed_paths_detects_changes_to_already_dirty_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    target.write_text("v2\n", encoding="utf-8")
    before = _capture_worktree_snapshot(repo)

    target.write_text("v3\n", encoding="utf-8")
    after = _capture_worktree_snapshot(repo)

    assert _compute_changed_paths(before, after) == ["notes.md"]


def test_compute_changed_paths_is_empty_when_nothing_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    before = _capture_worktree_snapshot(repo)
    after = _capture_worktree_snapshot(repo)

    assert _compute_changed_paths(before, after) == []


def test_extract_result_payload_reads_last_structured_payload():
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            '{"type":"text","part":{"type":"text","text":"{\\"outcome\\":\\"blocked\\",\\"summary\\":\\"first\\",\\"reason_code\\":\\"r1\\"}"}}',
            '{"type":"text","part":{"type":"text","text":"{\\"outcome\\":\\"needs_decision\\",\\"summary\\":\\"second\\",\\"reason_code\\":\\"r2\\",\\"decision_required\\":true}"}}',
        ]
    )

    payload = _extract_result_payload(raw)

    assert payload == {
        "outcome": "needs_decision",
        "summary": "second",
        "reason_code": "r2",
        "decision_required": True,
    }


def test_extract_result_payload_reads_marker_payload():
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            'STARDRIFTER_EXECUTION_RESULT_JSON={"outcome":"done","summary":"ok","reason_code":"r1","decision_required":false}',
            '{"type":"step_finish","reason":"stop"}',
        ]
    )

    payload = _extract_result_payload(raw)

    assert payload == {
        "outcome": "done",
        "summary": "ok",
        "reason_code": "r1",
        "decision_required": False,
    }


def test_extract_result_payload_reads_top_level_json_object():
    raw = "\n".join(
        [
            '{"outcome":"blocked","summary":"first","reason_code":"r1"}',
            "noise",
            '{"outcome":"needs_decision","summary":"second","reason_code":"r2","decision_required":true}',
        ]
    )

    payload = _extract_result_payload(raw)

    assert payload == {
        "outcome": "needs_decision",
        "summary": "second",
        "reason_code": "r2",
        "decision_required": True,
    }


def test_extract_result_payload_reads_json_embedded_in_text_event():
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            json.dumps(
                {
                    "type": "text",
                    "part": {
                        "type": "text",
                        "text": 'Final result: {"outcome":"blocked","summary":"awaiting repository context","reason_code":"awaiting_repository_context","decision_required":false}',
                    },
                }
            ),
        ]
    )

    payload = _extract_result_payload(raw)

    assert payload == {
        "outcome": "blocked",
        "summary": "awaiting repository context",
        "reason_code": "awaiting_repository_context",
        "decision_required": False,
    }


def test_extract_result_payload_details_counts_distinct_terminal_payloads():
    raw = "\n".join(
        [
            json.dumps(
                {
                    "type": "text",
                    "part": {
                        "type": "text",
                        "text": '{"outcome":"blocked","summary":"first","reason_code":"r1"}',
                    },
                }
            ),
            json.dumps(
                {
                    "type": "text",
                    "part": {
                        "type": "text",
                        "text": '{"outcome":"done","summary":"second","reason_code":"r2"}',
                    },
                }
            ),
        ]
    )

    details = _extract_result_payload_details(raw)

    assert details.payload == {
        "outcome": "done",
        "summary": "second",
        "reason_code": "r2",
    }
    assert details.terminal_payload_count == 2
    assert details.distinct_terminal_payload_count == 2
    assert details.marker_terminal_payload_count == 0


def test_extract_result_payload_details_prefers_marker_terminal_payload():
    raw = "\n".join(
        [
            '{"outcome":"blocked","summary":"top-level","reason_code":"r1"}',
            'STARDRIFTER_EXECUTION_RESULT_JSON={"outcome":"done","summary":"marker","reason_code":"r2","decision_required":false}',
        ]
    )

    details = _extract_result_payload_details(raw)

    assert details.payload == {
        "outcome": "done",
        "summary": "marker",
        "reason_code": "r2",
        "decision_required": False,
    }
    assert details.marker_terminal_payload_count == 1


def test_classify_multiple_terminal_payload_returns_blocked_payload_when_conflicting():
    raw = "\n".join(
        [
            '{"outcome":"blocked","summary":"first","reason_code":"r1"}',
            '{"outcome":"done","summary":"second","reason_code":"r2"}',
        ]
    )
    details = _extract_result_payload_details(raw)

    payload = _classify_multiple_terminal_payload(details)

    assert payload is not None
    assert payload["outcome"] == "blocked"
    assert payload["reason_code"] == "multiple-terminal-payloads"
    assert payload["decision_required"] is False


def test_classify_multiple_terminal_payload_ignores_duplicate_terminal_payloads():
    raw = "\n".join(
        [
            '{"outcome":"done","summary":"same","reason_code":"r1"}',
            '{"outcome":"done","summary":"same","reason_code":"r1"}',
        ]
    )
    details = _extract_result_payload_details(raw)

    payload = _classify_multiple_terminal_payload(details)

    assert payload is None


def test_classify_malformed_stream_payload_detects_json_parse_error_text():
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "name": "UnknownError",
                        "data": {
                            "message": "JSON parsing failed: Text: {.\nError message: JSON Parse error: Expected '}'"
                        },
                    },
                }
            ),
        ]
    )

    payload = _classify_malformed_stream_payload(raw)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "interrupted_retryable",
        "summary": "opencode emitted malformed JSON event/output; treating as retryable stream corruption",
        "decision_required": False,
    }


def test_classify_malformed_stream_payload_returns_none_for_normal_invalid_payload():
    raw = "opencode exited 0 but did not emit a valid structured result payload"

    payload = _classify_malformed_stream_payload(raw)

    assert payload is None


def test_classify_malformed_stream_payload_detects_unexpected_end_of_json_input():
    raw = "\n".join(
        [
            '{"type":"step_start","part":{"type":"step-start"}}',
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "name": "UnknownError",
                        "data": {
                            "message": "Unexpected end of JSON input while reading event payload"
                        },
                    },
                }
            ),
        ]
    )

    payload = _classify_malformed_stream_payload(raw)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "interrupted_retryable",
        "summary": "opencode emitted malformed JSON event/output; treating as retryable stream corruption",
        "decision_required": False,
    }


def test_classify_missing_terminal_payload_detects_event_stream_without_terminal_json():
    raw = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_use_id": "toolu_01",
                    "name": "shell_command",
                }
            ),
            json.dumps({"type": "step_finish", "reason": "stop"}),
        ]
    )

    payload = _classify_missing_terminal_payload(raw)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "missing-terminal-payload",
        "summary": "opencode emitted event stream but did not emit a terminal structured result payload",
        "decision_required": False,
    }


def test_classify_missing_terminal_payload_returns_none_for_plain_text():
    payload = _classify_missing_terminal_payload(
        "opencode exited 0 but did not emit a valid structured result payload"
    )

    assert payload is None


def test_classify_upstream_api_error_payload_detects_quota_exhausted_event():
    raw = "\n".join(
        [
            json.dumps(
                {
                    "type": "error",
                    "error": {
                        "name": "APIError",
                        "data": {
                            "message": "您的套餐已经到期或者额度用完，请去控制台充值",
                        },
                    },
                }
            ),
        ]
    )

    payload = _classify_upstream_api_error_payload(raw)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "upstream_api_error",
        "summary": "opencode failed due to upstream API error before producing a terminal payload",
        "decision_required": False,
    }


def test_classify_upstream_api_error_payload_returns_none_when_no_api_error():
    raw = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "tool_use", "name": "shell_command"}),
        ]
    )

    payload = _classify_upstream_api_error_payload(raw)

    assert payload is None


def test_build_timeout_payload_marks_needs_decision_false():
    payload = _build_timeout_payload(timeout_seconds=900)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "timeout",
        "summary": "opencode exceeded timeout after 900 seconds",
        "decision_required": False,
    }


def test_build_timeout_payload_includes_partial_output_summary():
    payload = _build_timeout_payload(
        timeout_seconds=900,
        partial_output="searching bridge adapters waiting on contract context",
    )

    assert payload["outcome"] == "blocked"
    assert payload["reason_code"] == "timeout"
    assert (
        payload["summary"]
        == "opencode exceeded timeout after 900 seconds; partial output: searching bridge adapters waiting on contract context"
    )
    assert payload["decision_required"] is False
    assert (
        payload["resume_context"]
        == "searching bridge adapters waiting on contract context"
    )


def test_build_prompt_highlights_allowed_paths_and_verification_scope():
    prompt = _build_prompt(
        {
            "id": "issue-139",
            "title": "[09-IMPL] Adapter registry",
            "lane": "Lane 09",
            "wave": "Wave0",
            "complexity": "medium",
            "source_issue_number": 139,
            "dod_json": {"story_issue_numbers": [130]},
            "body": (
                "## 修改范围\n\n"
                "- 允许修改：\n"
                "  - src/stardrifter_engine/bridge/*\n"
                "  - src/stardrifter_engine/services/*\n\n"
                "## 验证方式\n\n"
                "- [ ] PYTHONPATH=src python3 -m pytest -q tests/unit/test_unified_bridge_dispatcher.py\n"
                "\n## 参考\n\n"
                "- src/stardrifter_engine/models/protocol.py\n"
            ),
        }
    )

    assert "优先只阅读、修改和验证当前任务明确允许的路径" in prompt
    assert "任务目标（若有）如下" in prompt
    assert "src/stardrifter_engine/bridge/*" in prompt
    assert "tests/unit/test_unified_bridge_dispatcher.py" in prompt
    assert "src/stardrifter_engine/models/protocol.py" in prompt
    assert "仅供必要参考的任务正文片段如下" in prompt


def test_build_prompt_includes_bounded_mode_clause_when_enabled():
    prompt = _build_prompt(
        {
            "id": "issue-139",
            "title": "[09-IMPL] Adapter registry",
            "lane": "Lane 09",
            "wave": "Wave0",
            "complexity": "medium",
            "source_issue_number": 139,
            "dod_json": {"story_issue_numbers": [130]},
            "body": "## 修改范围\n\n- 允许修改：\n  - src/stardrifter_engine/bridge/*\n",
        },
        bounded_mode=True,
    )

    assert "bounded implementation mode" in prompt


def test_build_prompt_accepts_list_shaped_dod_json_without_crashing():
    prompt = _build_prompt(
        {
            "id": "issue-05h-01",
            "title": "Map manual control, autopilot, and command authority states",
            "lane": "lane:05",
            "wave": "wave-4",
            "complexity": "medium",
            "source_issue_number": 174,
            "dod_json": [
                "Authority state matrix documented for manual, autopilot, and command UI modes",
                "Current Godot entrypoints and Starsector target semantics are explicitly compared",
            ],
            "body": (
                "## 验收标准 (DoD)\n\n"
                "- [ ] Authority state matrix documented\n"
                "- [ ] Current Godot entrypoints and Starsector target semantics are explicitly compared\n"
            ),
        }
    )

    assert "GitHub Issue #174" in prompt
    assert "上级 Story: 无" in prompt
    assert "Authority state matrix documented" in prompt


def test_build_opencode_run_command_without_model_override(monkeypatch, tmp_path):
    monkeypatch.delenv("STARDRIFTER_OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("STARDRIFTER_OPENCODE_VARIANT", raising=False)

    command = _build_opencode_run_command(
        focus_dir=tmp_path, prompt="return terminal payload"
    )

    assert command == [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
        "return terminal payload",
    ]


def test_build_opencode_run_command_with_model_and_variant_override(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("STARDRIFTER_OPENCODE_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("STARDRIFTER_OPENCODE_VARIANT", "high")

    command = _build_opencode_run_command(
        focus_dir=tmp_path, prompt="return terminal payload"
    )

    assert command == [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
        "--model",
        "deepseek/deepseek-chat",
        "--variant",
        "high",
        "return terminal payload",
    ]


def test_load_timeout_seconds_uses_shorter_default_in_bounded_mode(monkeypatch):
    monkeypatch.delenv("STARDRIFTER_OPENCODE_TIMEOUT_SECONDS", raising=False)
    assert _load_timeout_seconds(bounded_mode=True) == 300


def test_load_hard_cap_seconds_defaults_to_three_times_timeout_in_bounded_mode(
    monkeypatch,
):
    monkeypatch.delenv("STARDRIFTER_OPENCODE_HARD_CAP_SECONDS", raising=False)

    assert _load_hard_cap_seconds(timeout_seconds=300, bounded_mode=True) == 900


def test_load_hard_cap_seconds_defaults_to_timeout_outside_bounded_mode(monkeypatch):
    monkeypatch.delenv("STARDRIFTER_OPENCODE_HARD_CAP_SECONDS", raising=False)

    assert _load_hard_cap_seconds(timeout_seconds=1200, bounded_mode=False) == 1200


def test_is_bounded_mode_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("STARDRIFTER_BOUNDED_EXECUTOR", "true")
    assert _is_bounded_mode_enabled() is True


def test_select_opencode_focus_dir_prefers_first_existing_allowed_directory(tmp_path):
    bridge_dir = tmp_path / "src" / "stardrifter_engine" / "bridge"
    bridge_dir.mkdir(parents=True)

    issue_body = (
        "## 修改范围\n\n"
        "- 允许修改：\n"
        "  - src/stardrifter_engine/bridge/*\n"
        "  - src/stardrifter_engine/services/*\n"
    )

    focus_dir = _select_opencode_focus_dir(project_dir=tmp_path, issue_body=issue_body)

    assert focus_dir == bridge_dir.resolve()


def test_build_salvaged_done_payload_returns_none_without_repo_changes():
    assert _build_salvaged_done_payload(changed_paths=[]) is None


def test_build_salvaged_done_payload_promotes_missing_payload_with_repo_changes():
    payload = _build_salvaged_done_payload(
        changed_paths=["src/stardrifter_engine/resources/runtime_state.py"]
    )

    assert payload == {
        "outcome": "done",
        "reason_code": "missing-terminal-payload-with-repo-change",
        "summary": (
            "opencode changed repository content but did not emit a terminal JSON payload; "
            "treating the attempt as done and deferring acceptance to verifier and commit safety checks."
        ),
        "decision_required": False,
    }


def test_ensure_contextweaver_index_runs_index_command(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "indexed"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)

    monkeypatch.setenv(
        "STARDRIFTER_CONTEXTWEAVER_REGISTRY_PATH",
        str(tmp_path / "registry.json"),
    )

    result = ensure_contextweaver_index_for_checkout(tmp_path, explicit_repo="repo")

    assert result is None
    assert captured["command"] == ["contextweaver", "index", str(tmp_path)]
    assert captured["cwd"] == str(tmp_path)


def test_ensure_contextweaver_index_returns_error_when_indexing_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: RepositoryIdentity(
            project_dir=project_dir.resolve(),
            repo_root=project_dir.resolve(),
            repository_id="control:repo",
            head_sha="abc123",
            is_dirty=False,
            snapshot_id="abc123",
        ),
    )
    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: "boom",
    )

    monkeypatch.setenv(
        "STARDRIFTER_CONTEXTWEAVER_REGISTRY_PATH",
        str(tmp_path / "registry.json"),
    )

    result = ensure_contextweaver_index_for_checkout(tmp_path, explicit_repo="repo")

    assert result == "boom"


def test_ensure_contextweaver_index_can_be_skipped_by_env(monkeypatch, tmp_path):
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("contextweaver index should have been skipped")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("STARDRIFTER_SKIP_CONTEXTWEAVER_INDEX", "true")

    result = ensure_contextweaver_index_for_checkout(tmp_path, explicit_repo="repo")

    assert result is None
    assert called is False


def test_non_terminal_payload_detection_rejects_background_research_status():
    payload = {
        "outcome": "blocked",
        "reason_code": "awaiting_background_research",
        "summary": "Background research is still running",
        "decision_required": False,
    }

    assert _is_non_terminal_payload(payload) is True


def test_non_terminal_payload_detection_allows_already_satisfied():
    payload = {
        "outcome": "already_satisfied",
        "reason_code": "already_done_in_repo",
        "summary": "The issue DoD is already met in the current repository state.",
        "decision_required": False,
    }

    assert _is_non_terminal_payload(payload) is False


def test_normalize_payload_maps_pause_for_input_to_needs_decision():
    payload = {
        "outcome": "blocked",
        "reason_code": "awaiting_user_input",
        "summary": "Paused and waiting for next step",
        "decision_required": False,
    }

    normalized = _normalize_payload(payload)

    assert normalized == {
        "outcome": "needs_decision",
        "reason_code": "awaiting_user_input",
        "summary": "Paused and waiting for next step",
        "decision_required": True,
    }


def test_classify_nonzero_exit_payload_marks_interrupted_retryable():
    payload = _classify_nonzero_exit_payload(returncode=130)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "interrupted_retryable",
        "summary": "opencode was interrupted before reaching a terminal result",
        "decision_required": False,
    }


def test_classify_nonzero_exit_payload_marks_tooling_error_for_generic_nonzero():
    payload = _classify_nonzero_exit_payload(returncode=7)

    assert payload == {
        "outcome": "blocked",
        "reason_code": "tooling_error",
        "summary": "opencode exited with code 7",
        "decision_required": False,
    }


def test_run_monitored_subprocess_extends_no_progress_deadline_on_checkpoint_and_wait():
    script = "\n".join(
        [
            "import json, sys, time",
            "def emit(payload):",
            "    print(json.dumps({'type': 'text', 'part': {'type': 'text', 'text': json.dumps(payload)}}), flush=True)",
            "emit({'execution_kind': 'checkpoint', 'phase': 'implementing', 'summary': 'started'})",
            "time.sleep(0.08)",
            "emit({'execution_kind': 'wait', 'wait_type': 'tool_result', 'summary': 'waiting'})",
            "time.sleep(0.08)",
            "emit({'outcome': 'done', 'summary': 'finished', 'reason_code': 'ok'})",
        ]
    )

    result = _run_monitored_subprocess(
        [sys.executable, "-u", "-c", script],
        cwd=None,
        no_progress_timeout_seconds=0.1,
        hard_cap_seconds=0.4,
    )

    assert result.timed_out is False
    assert result.returncode == 0
    assert result.progress_signal_count == 2
    assert result.last_progress_kind == "wait"
    assert "finished" in result.stdout


def test_run_monitored_subprocess_does_not_treat_plain_output_as_progress():
    script = "\n".join(
        [
            "import time",
            "print('heartbeat: still working', flush=True)",
            "time.sleep(0.2)",
            "print('done later', flush=True)",
        ]
    )

    result = _run_monitored_subprocess(
        [sys.executable, "-u", "-c", script],
        cwd=None,
        no_progress_timeout_seconds=0.1,
        hard_cap_seconds=0.4,
    )

    assert result.timed_out is True
    assert result.timeout_kind == "no_progress"
    assert result.progress_signal_count == 0


def test_run_monitored_subprocess_enforces_hard_cap_despite_progress_signals():
    script = "\n".join(
        [
            "import json, time",
            "def emit(payload):",
            "    print(json.dumps({'type': 'text', 'part': {'type': 'text', 'text': json.dumps(payload)}}), flush=True)",
            "for index in range(4):",
            "    emit({'execution_kind': 'checkpoint', 'phase': 'implementing', 'summary': f'progress-{index}'})",
            "    time.sleep(0.08)",
            "emit({'outcome': 'done', 'summary': 'too late', 'reason_code': 'ok'})",
        ]
    )

    result = _run_monitored_subprocess(
        [sys.executable, "-u", "-c", script],
        cwd=None,
        no_progress_timeout_seconds=0.1,
        hard_cap_seconds=0.25,
    )

    assert result.timed_out is True
    assert result.timeout_kind == "hard_cap"
    assert result.progress_signal_count >= 1


def test_extract_progress_signal_kind_recognizes_opencode_step_start():
    line = json.dumps({"type": "step_start", "timestamp": 1774796880316})
    assert _extract_progress_signal_kind(line) == "step_start"


def test_extract_progress_signal_kind_recognizes_opencode_step_finish():
    line = json.dumps({"type": "step_finish", "timestamp": 1774796880316})
    assert _extract_progress_signal_kind(line) == "step_finish"


def test_extract_progress_signal_kind_recognizes_opencode_message_start():
    line = json.dumps({"type": "message_start", "sessionID": "ses_abc123"})
    assert _extract_progress_signal_kind(line) == "message_start"


def test_extract_progress_signal_kind_recognizes_opencode_tool_start():
    line = json.dumps({"type": "tool_start", "tool": "grep"})
    assert _extract_progress_signal_kind(line) == "tool_start"


def test_extract_progress_signal_kind_recognizes_opencode_file_edit():
    line = json.dumps({"type": "file_edit", "file": "src/main.py"})
    assert _extract_progress_signal_kind(line) == "file_edit"


def test_extract_progress_signal_kind_ignores_unknown_event_types():
    line = json.dumps({"type": "unknown_event", "data": "something"})
    assert _extract_progress_signal_kind(line) is None


def test_extract_progress_signal_kind_ignores_plain_text():
    assert _extract_progress_signal_kind("just plain text output") is None


def test_build_timeout_payload_includes_resume_context():
    partial = "\n".join(
        [
            "reading issue body",
            "searching for control authority files",
            "found godot/ships/scripts/helpers/ship_direct_control_adapter.gd",
            "analyzing manual direct control gating logic",
        ]
    )
    payload = _build_timeout_payload(
        timeout_seconds=300,
        timeout_kind="no_progress",
        partial_output=partial,
    )

    assert payload["outcome"] == "blocked"
    assert payload["reason_code"] == "timeout"
    assert "resume_context" in payload
    assert "ship_direct_control_adapter" in payload["resume_context"]


def test_build_timeout_payload_omits_resume_context_when_no_partial():
    payload = _build_timeout_payload(
        timeout_seconds=300,
        timeout_kind="no_progress",
        partial_output="",
    )

    assert "resume_context" not in payload


def test_build_resume_context_from_output_preserves_last_lines():
    output = "\n".join(f"line-{index}" for index in range(100))
    context = _build_resume_context_from_output(output, max_chars=200)

    assert "line-99" in context
    assert len(context) <= 200 + 20


def test_build_resume_context_from_output_returns_empty_for_blank():
    assert _build_resume_context_from_output("") == ""
    assert _build_resume_context_from_output("   \n\n  ") == ""


def test_run_monitored_subprocess_treats_step_start_as_progress():
    script = "\n".join(
        [
            "import json, time",
            "print(json.dumps({'type': 'step_start', 'timestamp': 100}), flush=True)",
            "time.sleep(0.05)",
            "print(json.dumps({'type': 'step_finish', 'timestamp': 200}), flush=True)",
            "time.sleep(0.05)",
            "print(json.dumps({'outcome': 'done', 'summary': 'ok', 'reason_code': 'ok'}), flush=True)",
        ]
    )

    result = _run_monitored_subprocess(
        [sys.executable, "-u", "-c", script],
        cwd=None,
        no_progress_timeout_seconds=0.15,
        hard_cap_seconds=1.0,
    )

    assert result.timed_out is False
    assert result.progress_signal_count >= 1


def test_extract_wait_hint_finds_wait_payload_with_resume_hint():
    wait_payload = json.dumps(
        {
            "execution_kind": "wait",
            "wait_type": "subagent_result",
            "summary": "task too complex",
            "resume_hint": "split into doc/test/impl",
        }
    )
    raw_stream = "\n".join(
        [
            json.dumps(
                {"type": "text", "part": {"type": "text", "text": wait_payload}}
            ),
        ]
    )
    hint = _extract_wait_hint(raw_stream)

    assert hint is not None
    assert hint["execution_kind"] == "wait"
    assert "resume_hint" in hint


def test_extract_wait_hint_returns_none_when_no_wait_payload():
    raw_stream = "\n".join(
        [
            json.dumps({"type": "step_start", "timestamp": 100}),
            json.dumps({"type": "step_finish", "timestamp": 200}),
        ]
    )
    assert _extract_wait_hint(raw_stream) is None


def test_extract_wait_hint_ignores_wait_without_resume_hint():
    wait_payload = json.dumps(
        {
            "execution_kind": "wait",
            "wait_type": "subagent_result",
            "summary": "waiting for result",
        }
    )
    raw_stream = "\n".join(
        [
            json.dumps(
                {"type": "text", "part": {"type": "text", "text": wait_payload}}
            ),
        ]
    )
    assert _extract_wait_hint(raw_stream) is None
