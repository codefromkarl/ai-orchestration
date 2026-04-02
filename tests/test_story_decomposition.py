from typing import Any, cast

from taskplane import (
    story_decomposition as story_decomposition_module,
)
from taskplane.story_decomposition import (
    DecompositionExecutionResult,
    run_story_decomposition,
    run_shell_story_decomposer,
)
from taskplane.contextweaver_indexing import (
    FileIndexRegistry,
    IndexArtifactRecord,
)


def test_run_story_decomposition_promotes_story_to_active_when_tasks_appear():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "execution_status": "decomposing",
                "story_task_count": 0,
            },
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "execution_status": "decomposing",
                "story_task_count": 2,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=42,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created tasks",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.story_issue_number == 42
    assert result.final_execution_status == "active"
    assert result.projectable_task_count == 2
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 42,
        "execution_status": "active",
    }


def test_run_story_decomposition_marks_story_needs_refinement():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=42,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: {
            "story_issue_number": 42,
            "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
            "execution_status": "decomposing",
            "story_task_count": 0,
        },
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=False,
            outcome="needs_story_refinement",
            summary="story too broad",
            reason_code="story-boundary-invalid",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert captured["execution_status"] == "needs_story_refinement"


def test_run_story_decomposition_accepts_explicit_intake_refresher_object():
    captured: dict[str, object] = {}
    refresh_calls: list[tuple[object, str]] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    class ExplicitRefresher:
        def ingest(self, *, connection: object, repo: str) -> None:
            refresh_calls.append((connection, repo))

    snapshots = iter(
        [
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "execution_status": "decomposing",
                "story_task_count": 0,
            },
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "execution_status": "decomposing",
                "story_task_count": 2,
            },
        ]
    )

    repository = cast(Any, FakeRepository())
    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=42,
        repository=repository,
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created tasks",
        ),
        refresher=ExplicitRefresher(),
    )

    assert result.final_execution_status == "active"
    assert refresh_calls == [(repository, "codefromkarl/stardrifter")]
    assert captured["execution_status"] == "active"


def test_run_story_decomposition_marks_story_needs_refinement_when_no_projectable_tasks_are_created():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=41,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="model proposed no valid task issues",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert result.projectable_task_count == 0
    assert "no projectable tasks" in result.summary
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 41,
        "execution_status": "needs_story_refinement",
    }


def test_run_story_decomposition_retries_once_before_marking_needs_refinement_for_zero_tasks():
    captured: dict[str, object] = {}
    decomposer_calls: list[int] = []
    refresh_calls: list[str] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
        ]
    )

    def fake_decomposer(**kwargs):
        decomposer_calls.append(kwargs["story_issue_number"])
        return DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="model produced no projectable tasks",
            reason_code="no_projectable_tasks_generated",
        )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=41,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=fake_decomposer,
        refresher=lambda **kwargs: refresh_calls.append(kwargs["repo"]),
        fallback_generator=lambda **kwargs: False,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert result.projectable_task_count == 0
    assert result.reason_code == "zero_projectable_tasks_after_retry"
    assert len(decomposer_calls) == 2
    assert refresh_calls == ["codefromkarl/stardrifter", "codefromkarl/stardrifter"]
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 41,
        "execution_status": "needs_story_refinement",
    }


def test_run_story_decomposition_uses_fallback_generator_before_marking_needs_refinement():
    captured: dict[str, object] = {}
    fallback_calls: list[dict[str, object]] = []
    refresh_calls: list[str] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 2,
                "core_task_count": 1,
                "documentation_task_count": 1,
                "governance_task_count": 0,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=41,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="model proposed no valid task issues",
        ),
        refresher=lambda **kwargs: refresh_calls.append(kwargs["repo"]),
        fallback_generator=lambda **kwargs: fallback_calls.append(kwargs) or True,
    )

    assert result.final_execution_status == "active"
    assert result.projectable_task_count == 2
    assert result.summary == "model proposed no valid task issues"
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 41,
        "execution_status": "active",
    }
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["story_issue_number"] == 41
    assert refresh_calls == [
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
    ]


def test_run_story_decomposition_reports_structured_reason_for_doc_only_implementation_failure():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 22,
                "story_title": "[Story][01-B] Canonical geometry 入库",
                "story_body": "## Story Goal\n\n把 Starsector 星系几何数据转换并入库为 canonical authored truth\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 22,
                "story_title": "[Story][01-B] Canonical geometry 入库",
                "story_body": "## Story Goal\n\n把 Starsector 星系几何数据转换并入库为 canonical authored truth\n",
                "execution_status": "decomposing",
                "story_task_count": 3,
                "core_task_count": 0,
                "documentation_task_count": 3,
                "governance_task_count": 0,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created only doc tasks",
            reason_code="documentation_only_tasks",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert result.reason_code == "implementation_story_missing_core_tasks"
    assert captured["execution_status"] == "needs_story_refinement"
    assert "doc-only" in result.summary


def test_run_story_decomposition_default_fallback_is_disabled(monkeypatch):
    monkeypatch.delenv(
        "TASKPLANE_ENABLE_DEFAULT_DECOMPOSITION_FALLBACK", raising=False
    )

    assert story_decomposition_module._fallback_enabled() is False


def test_run_story_decomposition_default_fallback_can_activate_weak_verification_story(
    monkeypatch,
):
    captured: dict[str, object] = {}
    refresh_calls: list[str] = []
    created_payloads: list[dict[str, Any]] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 41,
                "story_title": "[Story][06-D] Verification closure",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 1,
                "core_task_count": 1,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
        ]
    )

    def fake_create_task_issues_from_payload(**kwargs):
        created_payloads.append(kwargs["payload"])
        return [103]

    monkeypatch.setenv("TASKPLANE_ENABLE_DEFAULT_DECOMPOSITION_FALLBACK", "1")
    monkeypatch.setattr(
        "taskplane.opencode_story_decomposer._create_task_issues_from_payload",
        fake_create_task_issues_from_payload,
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=41,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="model proposed no valid task issues",
        ),
        refresher=lambda **kwargs: refresh_calls.append(kwargs["repo"]),
    )

    assert result.final_execution_status == "active"
    assert result.projectable_task_count == 1
    assert result.summary == "model proposed no valid task issues"
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 41,
        "execution_status": "active",
    }
    assert refresh_calls == [
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
    ]
    assert len(created_payloads) == 1
    assert created_payloads[0]["tasks"][0]["title"].startswith("[06-TEST]")


def test_run_story_decomposition_default_fallback_can_activate_weak_implementation_story(
    monkeypatch,
):
    captured: dict[str, object] = {}
    refresh_calls: list[str] = []
    created_payloads: list[dict[str, Any]] = []

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Candidate Tasks\n\n- 开放问题：原 Issue 未列出候选 Task。\n",
                "execution_status": "decomposing",
                "story_task_count": 2,
                "core_task_count": 1,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
        ]
    )

    def fake_create_task_issues_from_payload(**kwargs):
        created_payloads.append(kwargs["payload"])
        return [104, 105]

    monkeypatch.setenv("TASKPLANE_ENABLE_DEFAULT_DECOMPOSITION_FALLBACK", "1")
    monkeypatch.setattr(
        "taskplane.opencode_story_decomposer._create_task_issues_from_payload",
        fake_create_task_issues_from_payload,
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=39,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="model proposed no valid task issues",
        ),
        refresher=lambda **kwargs: refresh_calls.append(kwargs["repo"]),
    )

    assert result.final_execution_status == "active"
    assert result.projectable_task_count == 2
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 39,
        "execution_status": "active",
    }
    assert refresh_calls == [
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
    ]
    assert len(created_payloads) == 1
    tasks = created_payloads[0]["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["title"].startswith("[06-IMPL]")
    assert tasks[1]["title"].startswith("[06-TEST]")


def test_run_story_decomposition_rejects_doc_only_tasks_for_implementation_story():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 22,
                "story_title": "[Story][01-B] Canonical geometry 入库",
                "story_body": "## Story Goal\n\n把 Starsector 星系几何数据转换并入库为 canonical authored truth\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 22,
                "story_title": "[Story][01-B] Canonical geometry 入库",
                "story_body": "## Story Goal\n\n把 Starsector 星系几何数据转换并入库为 canonical authored truth\n",
                "execution_status": "decomposing",
                "story_task_count": 3,
                "core_task_count": 0,
                "documentation_task_count": 3,
                "governance_task_count": 0,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created only doc tasks",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert captured["execution_status"] == "needs_story_refinement"
    assert "doc-only" in result.summary


def test_run_story_decomposition_rejects_governance_only_tasks_for_implementation_story():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Story Goal\n\n重写 projection runtime 与 verification path\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 39,
                "story_title": "[Story][06-B] Projection rewrite",
                "story_body": "## Story Goal\n\n重写 projection runtime 与 verification path\n",
                "execution_status": "decomposing",
                "story_task_count": 2,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 2,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=39,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created only governance tasks",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "needs_story_refinement"
    assert result.reason_code == "implementation_story_missing_core_tasks"
    assert captured["execution_status"] == "needs_story_refinement"
    assert "doc-only" in result.summary


def test_run_story_decomposition_allows_doc_only_tasks_for_documentation_story():
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    snapshots = iter(
        [
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "story_body": "## Story Goal\n\n生成 migration-knowledge 规格文档\n",
                "execution_status": "decomposing",
                "story_task_count": 0,
                "core_task_count": 0,
                "documentation_task_count": 0,
                "governance_task_count": 0,
            },
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "story_body": "## Story Goal\n\n生成 migration-knowledge 规格文档\n",
                "execution_status": "decomposing",
                "story_task_count": 3,
                "core_task_count": 0,
                "documentation_task_count": 3,
                "governance_task_count": 0,
            },
        ]
    )

    result = run_story_decomposition(
        repo="codefromkarl/stardrifter",
        story_issue_number=42,
        repository=cast(Any, FakeRepository()),
        story_loader=lambda **kwargs: next(snapshots),
        decomposer=lambda **kwargs: DecompositionExecutionResult(
            success=True,
            outcome="decomposed",
            summary="created doc tasks",
        ),
        refresher=lambda **kwargs: None,
    )

    assert result.final_execution_status == "active"
    assert captured["execution_status"] == "active"


def test_run_shell_story_decomposer_blocks_when_contextweaver_index_fails(
    monkeypatch, tmp_path
):
    gateway_calls: list[object] = []
    monkeypatch.setattr(
        story_decomposition_module,
        "ensure_contextweaver_index_for_checkout",
        lambda project_dir, explicit_repo=None: (
            gateway_calls.append((project_dir, explicit_repo)) or "index failed"
        ),
    )

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is False
    assert result.outcome == "blocked"
    assert result.reason_code == "contextweaver-index-failed"
    assert "contextweaver index failed" in result.summary
    assert gateway_calls == [(tmp_path.resolve(), "codefromkarl/stardrifter")]


def test_run_shell_story_decomposer_indexes_before_running_decomposer(
    monkeypatch, tmp_path
):
    events: list[object] = []

    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        story_decomposition_module,
        "ensure_contextweaver_index_for_checkout",
        lambda project_dir, explicit_repo=None: (
            events.append(("index", project_dir, explicit_repo)) or None
        ),
    )

    def fake_run(command, *args, **kwargs):
        events.append(("decomposer", command))
        return Completed(
            returncode=0,
            stdout='TASKPLANE_DECOMPOSITION_RESULT_JSON={"outcome":"decomposed","summary":"ok"}',
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is True
    assert result.outcome == "decomposed"
    assert events == [
        ("index", tmp_path.resolve(), "codefromkarl/stardrifter"),
        (
            "decomposer",
            "python3 -m taskplane.opencode_story_decomposer",
        ),
    ]


def test_run_shell_story_decomposer_reuses_ready_index_for_same_repo_snapshot(
    monkeypatch, tmp_path
):
    commands: list[object] = []
    workdir = tmp_path / "checkout-b"
    workdir.mkdir()
    registry_path = tmp_path / "registry.json"
    registry = FileIndexRegistry(registry_path)
    registry.upsert_artifact(
        IndexArtifactRecord(
            repository_id="control:codefromkarl/stardrifter",
            snapshot_id="abc123",
            repo_root=str((tmp_path / "repo").resolve()),
            schema_version="v1",
            status="ready",
        )
    )

    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(
        story_decomposition_module,
        "ensure_contextweaver_index_for_checkout",
        lambda project_dir, explicit_repo=None: None,
    )

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        return Completed(
            returncode=0,
            stdout='TASKPLANE_DECOMPOSITION_RESULT_JSON={"outcome":"decomposed","summary":"ok"}',
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=workdir,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is True
    assert commands == [
        "python3 -m taskplane.opencode_story_decomposer"
    ]


import subprocess


def test_run_shell_story_decomposer_blocks_when_opencode_times_out(
    monkeypatch, tmp_path
):
    commands: list[object] = []

    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        story_decomposition_module,
        "ensure_contextweaver_index_for_checkout",
        lambda project_dir, explicit_repo=None: None,
    )

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        raise subprocess.TimeoutExpired(command, timeout=45)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "45")

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is False
    assert result.outcome == "blocked"
    assert result.reason_code == "timeout"
    assert "45 seconds" in result.summary


def test_run_shell_story_decomposer_blocks_when_payload_is_missing_on_success(
    monkeypatch, tmp_path
):
    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, *args, **kwargs):
        if command[:2] == ["contextweaver", "index"]:
            return Completed(returncode=0, stdout="indexed")
        return Completed(returncode=0, stdout="not json")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is False
    assert result.outcome == "blocked"
    assert result.reason_code == "invalid-result-payload"
    assert "valid payload" in result.summary


def test_run_shell_story_decomposer_preserves_partial_output_on_timeout(
    monkeypatch, tmp_path
):
    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        story_decomposition_module,
        "ensure_contextweaver_index_for_checkout",
        lambda project_dir, explicit_repo=None: None,
    )

    def fake_run(command, *args, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            timeout=45,
            output="searching bridge runtime adapters\nwaiting on repository context",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "45")

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is False
    assert result.outcome == "blocked"
    assert result.reason_code == "timeout"
    assert "45 seconds" in result.summary
    assert (
        "searching bridge runtime adapters waiting on repository context"
        in result.summary
    )


def test_run_shell_story_decomposer_blocks_when_outcome_is_unsupported(
    monkeypatch, tmp_path
):
    class Completed:
        def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, *args, **kwargs):
        if command[:2] == ["contextweaver", "index"]:
            return Completed(returncode=0, stdout="indexed")
        return Completed(
            returncode=0,
            stdout='TASKPLANE_DECOMPOSITION_RESULT_JSON={"outcome":"thinking","summary":"still thinking","reason_code":"awaiting_context"}',
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_shell_story_decomposer(
        repo="codefromkarl/stardrifter",
        story_issue_number=22,
        story={
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
        },
        workdir=tmp_path,
        decomposer_command="python3 -m taskplane.opencode_story_decomposer",
    )

    assert result.success is False
    assert result.outcome == "blocked"
    assert result.reason_code == "unsupported-outcome"
    assert "unsupported outcome" in result.summary
