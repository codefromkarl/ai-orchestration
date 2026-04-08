from __future__ import annotations

from pathlib import Path

from taskplane.models import WorkItem
from taskplane.opencode_task_executor import _build_prompt as build_opencode_prompt
from taskplane.repository import InMemoryControlPlaneRepository
from taskplane.story_decomposition import run_story_decomposition
from taskplane.task_verifier import _resolve_verification_commands


def test_story_decomposition_defaults_to_local_noop_refresher() -> None:
    calls: list[str] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            calls.append(f"status:{repo}:{issue_number}:{execution_status}")

    snapshots = iter(
        [
            {
                "story_issue_number": 7,
                "story_title": "Local story",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
                "source_mode": "local_intake",
            },
            {
                "story_issue_number": 7,
                "story_title": "Local story",
                "execution_status": "decomposing",
                "story_task_count": 1,
                "core_task_count": 1,
                "documentation_task_count": 0,
                "governance_task_count": 0,
                "source_mode": "local_intake",
            },
        ]
    )

    result = run_story_decomposition(
        repo="owner/repo",
        story_issue_number=7,
        repository=FakeRepository(),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: __import__(
            "taskplane.story_decomposition", fromlist=["DecompositionExecutionResult"]
        ).DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created local tasks",
        ),
    )

    assert result.final_execution_status == "active"
    assert calls == ["status:owner/repo:7:active"]


def test_opencode_prompt_prefers_local_task_metadata_without_github_issue() -> None:
    row = {
        "id": "task-1",
        "title": "Build local auth flow",
        "lane": "general",
        "wave": "Direct",
        "complexity": "medium",
        "source_issue_number": None,
        "body": "",
        "dod_json": {
            "task_brief": "实现本地认证流程",
            "acceptance_criteria": ["登录成功", "未登录时禁止访问"],
            "verification_spec": {
                "commands": ["python3 -m pytest -q tests/test_auth.py"],
            },
            "planned_paths": ["src/auth.py"],
            "story_issue_numbers": [],
            "source_mode": "local_intake",
        },
    }

    prompt = build_opencode_prompt(row)

    assert "Taskplane work item task-1" in prompt
    assert "GitHub Issue #None" not in prompt
    assert "实现本地认证流程" in prompt
    assert "登录成功" in prompt
    assert "python3 -m pytest -q tests/test_auth.py" in prompt


def test_verifier_prefers_local_verification_spec(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_auth.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    commands = _resolve_verification_commands(
        title="Build local auth flow",
        body="",
        project_dir=tmp_path,
        metadata={
            "verification_spec": {
                "commands": ["python3 -m pytest -q tests/test_auth.py"],
            }
        },
    )

    assert commands == [["python3", "-m", "pytest", "-q", "tests/test_auth.py"]]


def test_local_intake_promotion_creates_work_items_without_source_issue_numbers() -> (
    None
):
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    from taskplane.intake_service import NaturalLanguageIntakeService

    def fake_analyzer(
        *, repo: str, conversation: list[dict[str, str]]
    ) -> dict[str, object]:
        del repo, conversation
        return {
            "outcome": "ready_for_review",
            "summary": "本地模式任务已准备好。",
            "promotion_mode": "local",
            "epic": {"title": "Local epic", "lane": "general"},
            "stories": [
                {
                    "story_key": "S1",
                    "title": "Local story",
                    "lane": "general",
                    "complexity": "medium",
                    "tasks": [
                        {
                            "task_key": "T1",
                            "title": "Implement local auth",
                            "lane": "general",
                            "wave": "Direct",
                            "task_type": "core_path",
                            "blocking_mode": "soft",
                            "planned_paths": ["src/auth.py"],
                            "dod": ["登录成功"],
                            "verification": ["python3 -m pytest -q tests/test_auth.py"],
                        }
                    ],
                }
            ],
        }

    service = NaturalLanguageIntakeService(
        repository=repository, analyzer=fake_analyzer
    )
    intent = service.submit_intent(repo="owner/repo", prompt="实现本地认证")
    promoted = service.approve_intent(intent_id=intent.id, approver="operator")

    assert promoted.status == "promoted"
    work_items = repository.list_work_items()
    assert len(work_items) == 1
    assert work_items[0].source_issue_number is None
    assert work_items[0].wave == "Direct"
    assert work_items[0].repo == "owner/repo"


def test_work_item_supports_local_metadata_keys() -> None:
    item = WorkItem(
        id="task-local-1",
        title="Local task",
        lane="general",
        wave="Direct",
        status="ready",
        repo="owner/repo",
    )

    assert item.repo == "owner/repo"


def test_claude_code_controlled_executor_runs_via_supported_module(
    tmp_path: Path,
) -> None:
    from taskplane.adapters import build_controlled_executor

    executor = build_controlled_executor(
        workdir=tmp_path,
        command_template="python3 -m taskplane.claude_code_task_executor",
    )

    assert executor is not None
