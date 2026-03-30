import json
from pathlib import Path
import os
import subprocess
from typing import Any, cast

from stardrifter_orchestration_mvp.opencode_story_decomposer import (
    _build_prompt,
    _create_task_issues_from_payload,
    _extract_result_payload,
    _render_task_issue_body,
)
from stardrifter_orchestration_mvp.contextweaver_indexing import (
    RepositoryIdentity,
    ensure_contextweaver_index_for_checkout,
)


def test_build_prompt_requires_task_creation_or_refinement():
    prompt = _build_prompt(
        repo="codefromkarl/stardrifter",
        row={
            "issue_number": 42,
            "title": "[Story][W0-A] 文档分析与知识蒸馏",
            "body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
            "story_task_count": 0,
        },
        project_dir=Path("/repo/root"),
    )

    assert "2-4 个“当前阶段最小可执行”的 Task 方案" in prompt
    assert "不要创建 GitHub issue" in prompt
    assert "needs_story_refinement" in prompt
    assert "不得返回 decomposed" in prompt
    assert "不得只创建 DOC task" in prompt
    assert "无法指出任何代码或测试落点" in prompt
    assert "Candidate Tasks" in prompt
    assert "只以“当前已投影 task 数”为准" in prompt
    assert "如果当前已投影 task 数为 0，你必须创建新的 Task" in prompt
    assert '"tasks":' in prompt


def test_render_task_issue_body_includes_required_sections():
    body = _render_task_issue_body(
        story_issue_number=22,
        story_title="[Story][01-B] Canonical geometry 入库",
        goal="补全 canonical geometry authored 数据入库",
        allowed_paths=[
            "data/campaign/authored/*",
            "src/stardrifter_engine/campaign/authoring_conversion.py",
        ],
        dod=["authoring 数据完整", "转换验证通过"],
        verification=["运行 conversion 测试", "同步 Story 状态"],
        references=["docs/domains/01-campaign-topology/execution-plan.md#task-01-b"],
    )

    assert "## 背景" in body
    assert "## 上级 Story" in body
    assert "- #22" in body
    assert "## 修改范围" in body
    assert "data/campaign/authored/*" in body
    assert "## 验收标准 (DoD)" in body
    assert "## 验证方式" in body
    assert "## 参考" in body


def test_create_task_issues_from_payload_creates_pending_lane_task(
    monkeypatch, tmp_path
):
    captured: dict[str, Any] = {}
    drafts: list[Any] = []

    class Completed:
        returncode = 0
        stdout = "https://github.com/codefromkarl/stardrifter/issues/88\n"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")

    class FakeRepository:
        def record_task_spec_draft(self, draft):
            drafts.append(draft)
            return 1

    issue_numbers = _create_task_issues_from_payload(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story_row={
            "issue_number": 22,
            "title": "[Story][01-B] Canonical geometry 入库",
            "lane": "lane:01",
        },
        payload={
            "outcome": "decomposed",
            "tasks": [
                {
                    "title": "[01-IMPL] 补全 canonical geometry authored 数据入库",
                    "complexity": "medium",
                    "goal": "补全 canonical geometry authored 数据入库",
                    "allowed_paths": [
                        "data/campaign/authored/*",
                        "src/stardrifter_engine/campaign/authoring_conversion.py",
                    ],
                    "dod": ["authoring 数据完整", "转换验证通过"],
                    "verification": ["运行 conversion 测试", "同步 Story 状态"],
                    "references": [
                        "docs/domains/01-campaign-topology/execution-plan.md#task-01-b"
                    ],
                }
            ],
        },
        project_dir=tmp_path,
        repository=FakeRepository(),
    )

    assert issue_numbers == [88]
    assert captured["cwd"] == str(tmp_path)
    command = cast(list[str], captured["command"])
    assert command[:7] == [
        "gh",
        "issue",
        "create",
        "--repo",
        "codefromkarl/stardrifter",
        "--title",
        "[01-IMPL] 补全 canonical geometry authored 数据入库",
    ]
    assert "--body" in command
    assert "## 上级 Story" in command[8]
    assert command[-8:] == [
        "--label",
        "task",
        "--label",
        "lane:01",
        "--label",
        "complexity:medium",
        "--label",
        "status:pending",
    ]
    assert "GITHUB_TOKEN" not in cast(dict[str, str], captured["env"])
    assert len(drafts) == 1
    assert drafts[0].story_issue_number == 22
    assert drafts[0].title == "[01-IMPL] 补全 canonical geometry authored 数据入库"


def test_ensure_contextweaver_index_runs_index_command(monkeypatch, tmp_path):
    captured: dict[str, Any] = {}

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


def test_load_timeout_seconds_from_env(monkeypatch):
    from stardrifter_orchestration_mvp.opencode_story_decomposer import (
        _load_timeout_seconds,
    )

    monkeypatch.setenv("STARDRIFTER_OPENCODE_TIMEOUT_SECONDS", "45")

    assert _load_timeout_seconds() == 45


def test_extract_result_payload_reads_last_json_object():
    output = "\n".join(
        [
            '{"outcome":"blocked","summary":"first","reason_code":"r1"}',
            "non-json noise",
            '{"outcome":"needs_story_refinement","summary":"second","reason_code":"story-boundary-invalid"}',
        ]
    )

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "needs_story_refinement",
        "summary": "second",
        "reason_code": "story-boundary-invalid",
    }


def test_extract_result_payload_prefers_marker_payload_over_trailing_step_json():
    output = "\n".join(
        [
            '{"type":"step_start"}',
            'STARDRIFTER_DECOMPOSITION_RESULT_JSON={"outcome":"blocked","summary":"awaiting repository context","reason_code":"awaiting_repository_context"}',
            '{"type":"step_finish","reason":"stop"}',
        ]
    )

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "blocked",
        "summary": "awaiting repository context",
        "reason_code": "awaiting_repository_context",
    }


def test_extract_result_payload_reads_json_embedded_in_text_event():
    embedded = json.dumps(
        {
            "outcome": "blocked",
            "summary": "awaiting repository context",
            "reason_code": "awaiting_repository_context",
        },
        ensure_ascii=False,
    )
    output = "\n".join(
        [
            '{"type":"step_start"}',
            json.dumps(
                {"type": "text", "part": {"text": embedded}}, ensure_ascii=False
            ),
            '{"type":"step_finish","reason":"stop"}',
        ]
    )

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "blocked",
        "summary": "awaiting repository context",
        "reason_code": "awaiting_repository_context",
    }


def test_extract_result_payload_maps_deferred_text_to_blocked_reason():
    payload = _extract_result_payload(
        "Waiting on repository document discovery before I can continue."
    )

    assert payload == {
        "outcome": "blocked",
        "summary": "decomposer attempted deferred/background-only reasoning instead of returning a final result",
        "reason_code": "deferred-result-not-allowed",
    }


def test_build_prompt_forbids_deferred_answers():
    prompt = _build_prompt(
        repo="codefromkarl/stardrifter",
        row={
            "issue_number": 130,
            "title": "[Story][09-A] Unified Bridge API",
            "body": "story body",
            "story_task_count": 0,
        },
        project_dir=Path("/repo/root"),
    )

    assert "你可以输出两种 JSON" in prompt
    assert 'execution_kind":"checkpoint"' in prompt
    assert 'execution_kind":"wait"' in prompt
